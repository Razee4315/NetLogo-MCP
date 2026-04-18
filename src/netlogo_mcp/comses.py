"""CoMSES Net API client + safe archive handling.

Pure HTTP + filesystem logic. No MCP coupling. Easy to unit test with
`httpx.MockTransport`.

Covered here:
- `ComsesClient`: async HTTP client for search, metadata, HEAD, and stream download.
- Retry policy: only on 502/503/504/network errors; never on 4xx.
- Safe zip extraction: path validation, zip-bomb guard, atomic temp-to-final move.
- Completion marker: `.comses_complete` written on success; cache only trusted if present.
- `resolve_latest`: turns "latest" into a concrete version string before any cache path.
- Language detection from `codemeta.json` with extension fallback.
- Deterministic NetLogo-file selection rule (Section 4.4 of COMSES_PLAN.md).

Everything that can be called from a tool is async.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import httpx

BASE_URL = "https://www.comses.net"

# ── Retry / network policy ────────────────────────────────────────────────────

RETRY_STATUSES = frozenset({502, 503, 504})
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = (1.0, 2.0)  # len must equal MAX_RETRIES
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Retriable network exception types (from httpx).
_RETRIABLE_EXCS: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.WriteError,
)


class ComsesError(Exception):
    """Any COMSES client or extraction failure."""


class ComsesHTTPError(ComsesError):
    """HTTP-level error against the COMSES API (non-retriable 4xx, or retries exhausted)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ComsesSafetyError(ComsesError):
    """A zip member failed safety validation (traversal, absolute path, zip bomb)."""


# ── Client ────────────────────────────────────────────────────────────────────


@dataclass
class StreamResult:
    """Result of a streamed download to disk."""

    path: Path
    bytes_written: int
    content_type: str


class ComsesClient:
    """Async client for the CoMSES Net HTTP API.

    Intentionally thin. Parsing / shape-shifting is done by callers, not here.
    The only intelligence this class owns is:
    - retry rules (per `_request_with_retry`)
    - stream-time byte cap (per `stream_download`)
    - the right `Accept`/query-string dance for JSON endpoints
    """

    BASE_URL: str = BASE_URL

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        base_url: str | None = None,
    ) -> None:
        self._base_url = (base_url or self.BASE_URL).rstrip("/")
        self._owned = client is None
        self._client = client or httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": "NetLogo-MCP/0.1 (+https://github.com/Razee4315/NetLogo-MCP)"
            },
        )

    async def aclose(self) -> None:
        if self._owned:
            await self._client.aclose()

    async def __aenter__(self) -> ComsesClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # ── Retry core ───────────────────────────────────────────────────────────

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        max_retries: int = MAX_RETRIES,
        **kwargs: object,
    ) -> httpx.Response:
        """Execute an HTTP request with the documented retry policy.

        Retriable:
        - HTTP 502 / 503 / 504
        - httpx.ConnectError / ReadError / ReadTimeout / ConnectTimeout / WriteError

        Not retriable:
        - Any 4xx (client-side / missing data — retry won't change it)
        - Any 2xx (even with unexpected Content-Type — caller decides)
        - Any other 5xx (500 etc. — caller decides)
        """
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.request(method, url, **kwargs)  # type: ignore[arg-type]
            except _RETRIABLE_EXCS as exc:
                last_exc = exc
                if attempt >= max_retries:
                    raise ComsesHTTPError(
                        f"Network error after {max_retries + 1} attempts: {exc!r}"
                    ) from exc
                await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
                continue

            if resp.status_code in RETRY_STATUSES and attempt < max_retries:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
                continue

            return resp

        # Defensive: loop exited without returning or raising.
        raise ComsesHTTPError(
            f"Exhausted retries: {last_exc!r}" if last_exc else "Exhausted retries"
        )

    # ── JSON endpoints ───────────────────────────────────────────────────────

    async def search(self, query: str = "", page: int = 1) -> dict:
        """Paginated codebase search. `query=""` browses everything."""
        params: dict[str, str | int] = {"format": "json", "page": page}
        if query:
            params["query"] = query
        resp = await self._request_with_retry(
            "GET", f"{self._base_url}/codebases/", params=params
        )
        return _json_or_raise(resp, "search")

    async def get_codebase(self, identifier: str) -> dict:
        resp = await self._request_with_retry(
            "GET",
            f"{self._base_url}/codebases/{identifier}/",
            params={"format": "json"},
        )
        return _json_or_raise(resp, "get_codebase")

    async def get_release(self, identifier: str, version: str) -> dict:
        resp = await self._request_with_retry(
            "GET",
            f"{self._base_url}/codebases/{identifier}/releases/{version}/",
            params={"format": "json"},
        )
        return _json_or_raise(resp, "get_release")

    async def resolve_latest(self, identifier: str, version: str) -> str:
        """Turn "latest" into a concrete version string; passthrough otherwise.

        Snapshot semantics: this resolution is pinned for the current call.
        If the author publishes a newer version mid-download, the in-flight
        operation stays on the version resolved here; the next caller asking
        for "latest" will resolve again and may get a newer one.
        """
        if version != "latest":
            return version
        data = await self.get_codebase(identifier)
        latest = data.get("latestVersionNumber")
        if not latest:
            raise ComsesError(
                f"Codebase {identifier} has no latestVersionNumber — "
                "cannot resolve 'latest'."
            )
        return str(latest)

    # ── Download (HEAD + streamed body) ──────────────────────────────────────

    def _download_url(self, identifier: str, version: str) -> str:
        """Build a UUID-based download URL (fallback path).

        Real COMSES requires the numeric codebase ID (from the release's
        `absoluteUrl`) for /download/ to return a zip — UUID 404s. Prefer
        `resolve_download_url` over this when you have release metadata.
        """
        return f"{self._base_url}/codebases/{identifier}/releases/{version}/download/"

    async def resolve_download_url(self, identifier: str, version: str) -> str:
        """Return the correct /download/ URL for a release.

        COMSES accepts the UUID for metadata endpoints but requires the
        numeric codebase id for the download endpoint. Fetch the release
        once and build the URL from its `absoluteUrl` (e.g.
        `/codebases/5445/releases/2.0.0/`).
        """
        rel = await self.get_release(identifier, version)
        abs_url = rel.get("absoluteUrl")
        if isinstance(abs_url, str) and abs_url.startswith("/"):
            return f"{self._base_url}{abs_url.rstrip('/')}/download/"
        # Fallback to UUID path if the field is missing — may 404.
        return self._download_url(identifier, version)

    async def head_download(
        self, identifier: str, version: str, *, url: str | None = None
    ) -> tuple[int | None, str]:
        """Return (content_length_or_None, content_type).

        `Content-Length` is advisory — some responses omit it. The real cap is
        enforced at stream time. Pass `url` to skip URL resolution when the
        caller already knows the correct /download/ path.
        """
        target = url or self._download_url(identifier, version)
        resp = await self._request_with_retry("HEAD", target)
        if resp.status_code >= 400:
            raise ComsesHTTPError(
                f"HEAD download failed: HTTP {resp.status_code}",
                status=resp.status_code,
            )
        cl = resp.headers.get("Content-Length")
        try:
            length = int(cl) if cl is not None else None
        except ValueError:
            length = None
        return length, resp.headers.get("Content-Type", "")

    async def stream_download(
        self,
        identifier: str,
        version: str,
        dest: Path,
        *,
        max_bytes: int,
        url: str | None = None,
    ) -> StreamResult:
        """Stream the archive to `dest`, aborting if it exceeds `max_bytes`.

        Returns a `StreamResult`. Raises `ComsesHTTPError` if the response is
        non-zip, non-2xx, or the stream exceeds the cap. On abort, the partial
        file is deleted. Pass `url` to override the default UUID-based path
        (real COMSES requires the numeric codebase id in /download/).
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url is None:
            url = self._download_url(identifier, version)

        # Streaming uses the underlying client directly. We still apply the
        # retry policy for the initial response; an interrupted in-flight
        # stream is *not* retried (partial bytes already written).
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with self._client.stream("GET", url) as resp:
                    if resp.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                        await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
                        continue
                    if resp.status_code >= 400:
                        raise ComsesHTTPError(
                            f"Download failed: HTTP {resp.status_code}",
                            status=resp.status_code,
                        )

                    content_type = resp.headers.get("Content-Type", "")
                    if "zip" not in content_type.lower():
                        # COMSES sometimes returns an HTML interstitial instead
                        # of a zip. Treat that as a hard failure — retry won't
                        # fix a policy-level interstitial.
                        raise ComsesHTTPError(
                            f"Expected zip, got Content-Type={content_type!r}. "
                            "You may need to download this archive manually."
                        )

                    written = 0
                    try:
                        with dest.open("wb") as fh:
                            async for chunk in resp.aiter_bytes():
                                if not chunk:
                                    continue
                                written += len(chunk)
                                if written > max_bytes:
                                    # Abort the stream and delete partial file.
                                    raise ComsesHTTPError(
                                        f"Download exceeded cap ({max_bytes} bytes) "
                                        f"at {written} bytes — aborted."
                                    )
                                fh.write(chunk)
                    except Exception:
                        # Any failure mid-stream: clean up the partial file.
                        try:
                            dest.unlink(missing_ok=True)
                        except OSError:
                            pass
                        raise

                    return StreamResult(
                        path=dest, bytes_written=written, content_type=content_type
                    )
            except _RETRIABLE_EXCS as exc:
                last_exc = exc
                if attempt >= MAX_RETRIES:
                    raise ComsesHTTPError(
                        f"Network error streaming download: {exc!r}"
                    ) from exc
                await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
                continue

        raise ComsesHTTPError(
            f"Exhausted retries on stream download: {last_exc!r}"
            if last_exc
            else "Exhausted retries on stream download"
        )


def _json_or_raise(resp: httpx.Response, op: str) -> dict:
    if resp.status_code >= 400:
        raise ComsesHTTPError(f"{op}: HTTP {resp.status_code}", status=resp.status_code)
    ct = resp.headers.get("Content-Type", "")
    if "json" not in ct.lower():
        raise ComsesHTTPError(f"{op}: expected JSON, got Content-Type={ct!r}")
    try:
        data: dict = resp.json()
    except json.JSONDecodeError as exc:
        raise ComsesHTTPError(f"{op}: response was not valid JSON: {exc}") from exc
    return data


# ── Zip safety + atomic extract ───────────────────────────────────────────────

COMPLETION_MARKER = ".comses_complete"


def is_cache_trusted(cache_dir: Path) -> bool:
    """A cache directory is trusted only if its `.comses_complete` marker is present."""
    return cache_dir.is_dir() and (cache_dir / COMPLETION_MARKER).is_file()


def _member_is_safe(target_root: Path, member: str) -> bool:
    """Return True iff this zip member is safe to extract under `target_root`.

    Rejects traversal (`..`), absolute paths, Windows drive letters.
    """
    # Normalize separators. Zips use forward slash by spec, but be defensive.
    name = member.replace("\\", "/").strip()
    if not name:
        return False
    # Absolute / rooted paths, Windows drives, explicit ".." segments.
    if name.startswith("/") or name.startswith("\\"):
        return False
    if len(name) >= 2 and name[1] == ":":
        return False
    parts = PurePosixPath(name).parts
    if any(p == ".." for p in parts):
        return False

    candidate = (target_root / name).resolve()
    root_resolved = target_root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return False
    return True


def validate_zip_members(zf: zipfile.ZipFile, target_root: Path) -> None:
    """Raise `ComsesSafetyError` if any member would escape `target_root`."""
    for info in zf.infolist():
        if not _member_is_safe(target_root, info.filename):
            raise ComsesSafetyError(f"Unsafe zip member rejected: {info.filename!r}")


def check_zip_bomb(zf: zipfile.ZipFile, max_bytes: int) -> int:
    """Sum uncompressed sizes. Raise if total > 2 × max_bytes.

    The 2× margin is a cheap guard against high-ratio zip bombs where the
    compressed bytes were under the download cap but the expanded tree is
    massive. Returns the computed total for logging.
    """
    total = sum(info.file_size for info in zf.infolist())
    if total > 2 * max_bytes:
        raise ComsesSafetyError(
            f"Archive would expand to {total} bytes, "
            f"more than 2 × download cap ({max_bytes}). Refusing."
        )
    return total


def safe_extract_zip(
    archive_path: Path,
    final_dir: Path,
    *,
    max_bytes: int,
    tmp_root: Path | None = None,
) -> Path:
    """Safely extract `archive_path` to `final_dir`.

    Pipeline:
      1. Open zip, validate every member, check zip-bomb threshold.
      2. Extract to a sibling temp directory.
      3. Atomically `shutil.move` temp → `final_dir`.
      4. Write `.comses_complete` marker.

    Race-safe: if `final_dir` appeared between steps 2 and 3 (another writer),
    we check its marker — if marked we discard our temp and keep theirs; if
    unmarked we assume orphan, wipe it, and retry the move once.
    """
    tmp_root = tmp_root or final_dir.parent / ".tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)

    # Unique-ish tmp dir; pid keeps it obvious which process owned it.
    tmp_dir = tmp_root / f"extract-{os.getpid()}-{final_dir.name}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)

    try:
        with zipfile.ZipFile(archive_path) as zf:
            validate_zip_members(zf, tmp_dir)
            check_zip_bomb(zf, max_bytes)
            zf.extractall(tmp_dir)

        _move_or_reconcile(tmp_dir, final_dir)

        (final_dir / COMPLETION_MARKER).write_text("ok\n", encoding="utf-8")
        return final_dir
    except Exception:
        # Leave tmp_dir for debugging? No — silent cleanup avoids littering cache.
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    finally:
        # If tmp_dir still exists (e.g. move succeeded but rename consumed it),
        # this is a no-op.
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _move_or_reconcile(tmp_dir: Path, final_dir: Path) -> None:
    """Move `tmp_dir` to `final_dir`, handling the race with a peer writer.

    See Section 4.6 cache trust table. Retries the move at most once.
    """
    if not final_dir.exists():
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_dir), str(final_dir))
        return

    # Final dir already there. Check marker.
    if (final_dir / COMPLETION_MARKER).is_file():
        # Peer writer finished; keep theirs, discard ours.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return

    # Unmarked orphan — wipe and retry once.
    shutil.rmtree(final_dir, ignore_errors=True)
    shutil.move(str(tmp_dir), str(final_dir))


# ── Post-extract inspection ───────────────────────────────────────────────────


# Language hints derived from codemeta.json or extension fallback.
_EXT_TO_LANGUAGE = {
    ".nlogo": "NetLogo",
    ".nlogox": "NetLogo",
    ".py": "Python",
    ".r": "R",
    ".R": "R",
    ".jl": "Julia",
    ".java": "Java",
    ".m": "MATLAB",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
}


def detect_language(extracted_dir: Path) -> str:
    """Best-effort language detection from codemeta.json, then extension scan."""
    codemeta = extracted_dir / "codemeta.json"
    if codemeta.is_file():
        try:
            data = json.loads(codemeta.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            lang = data.get("programmingLanguage")
            # codemeta allows string or object or list
            if isinstance(lang, str) and lang.strip():
                return lang.strip()
            if isinstance(lang, dict):
                name = lang.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()
            if isinstance(lang, list) and lang:
                first = lang[0]
                if isinstance(first, str):
                    return first
                if isinstance(first, dict):
                    first_name = first.get("name")
                    if isinstance(first_name, str):
                        return first_name

    # Fallback: whichever recognized extension appears most under code/ or root.
    counts: dict[str, int] = {}
    for p in extracted_dir.rglob("*"):
        if p.is_file():
            lang = _EXT_TO_LANGUAGE.get(p.suffix)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return "Unknown"
    return max(counts.items(), key=lambda kv: kv[1])[0]


def find_netlogo_files(extracted_dir: Path) -> list[Path]:
    """All `.nlogo` / `.nlogox` files in the extracted archive, sorted."""
    found = [
        p
        for p in extracted_dir.rglob("*")
        if p.is_file() and p.suffix in (".nlogo", ".nlogox")
    ]
    # Stable alphabetical order by relative path.
    found.sort(key=lambda p: p.relative_to(extracted_dir).as_posix())
    return found


def select_netlogo_file(netlogo_files: list[Path], extracted_dir: Path) -> Path | None:
    """Deterministic NetLogo file selection (Section 4.4 of COMSES_PLAN).

    1. Exactly one candidate → use it.
    2. Prefer files under `code/`.
    3. Prefer `.nlogox` over `.nlogo`.
    4. Lex-largest relative path as a pure tie-breaker (not semver-smart).
    """
    if not netlogo_files:
        return None
    if len(netlogo_files) == 1:
        return netlogo_files[0]

    def rel_parts(p: Path) -> tuple[str, ...]:
        return p.relative_to(extracted_dir).parts

    # Step 2: prefer under code/.
    under_code = [
        p for p in netlogo_files if rel_parts(p) and rel_parts(p)[0] == "code"
    ]
    candidates = under_code if under_code else netlogo_files

    # Step 3: prefer .nlogox.
    nlogox = [p for p in candidates if p.suffix == ".nlogox"]
    if nlogox:
        candidates = nlogox

    # Step 4: lex-largest relative path.
    candidates.sort(key=lambda p: p.relative_to(extracted_dir).as_posix())
    return candidates[-1]


_ODD_NAME_PATTERNS = ("ODD", "odd", "documentation", "README", "readme")
_ODD_TEXT_EXTS = (".md", ".txt")
_ODD_BINARY_EXTS = (".pdf", ".docx", ".odt", ".doc")


def _find_odd_by_exts(extracted_dir: Path, exts: tuple[str, ...]) -> Path | None:
    """Shared scanner for `find_odd_doc` / `find_odd_doc_binary`."""
    docs_dir = extracted_dir / "docs"
    search_roots = [docs_dir, extracted_dir] if docs_dir.is_dir() else [extracted_dir]
    for root in search_roots:
        if not root.is_dir():
            continue
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if not p.is_file():
                continue
            if p.suffix.lower() not in exts:
                continue
            name = p.name
            for pat in _ODD_NAME_PATTERNS:
                if name.startswith(pat):
                    return p
    # Second pass: match anywhere in the filename (e.g. "FNNR ABM - ODD.pdf").
    for root in search_roots:
        if not root.is_dir():
            continue
        for p in sorted(root.iterdir(), key=lambda x: x.name):
            if not p.is_file() or p.suffix.lower() not in exts:
                continue
            lower = p.name.lower()
            if any(pat.lower() in lower for pat in _ODD_NAME_PATTERNS):
                return p
    return None


def find_odd_doc(extracted_dir: Path) -> Path | None:
    """First matching text ODD / documentation file, None if none found."""
    return _find_odd_by_exts(extracted_dir, _ODD_TEXT_EXTS)


def find_odd_doc_binary(extracted_dir: Path) -> Path | None:
    """First matching ODD / documentation file in a binary format (PDF/DOCX/etc.).

    Useful so the tool can tell the AI "an ODD exists but is a PDF — the
    user will need to open it in a viewer." The file itself is NOT read
    by read_comses_files (v1 scope limit).
    """
    return _find_odd_by_exts(extracted_dir, _ODD_BINARY_EXTS)


@dataclass
class DownloadOutcome:
    """Result of a high-level download_release call.

    Consumed by both `download_comses_model` and `open_comses_model` tools.
    """

    identifier: str
    resolved_version: str
    extracted_path: Path
    cached: bool
    language: str
    netlogo_files: list[Path]
    selected_netlogo_file: Path | None
    code_files: list[Path]
    odd_doc: Path | None
    odd_doc_binary: Path | None
    license_name: str | None
    title: str | None


async def download_release(
    client: ComsesClient,
    identifier: str,
    version: str,
    *,
    cache_root: Path,
    max_bytes: int,
) -> DownloadOutcome:
    """End-to-end: resolve, check cache, HEAD, stream, safely extract, inspect.

    Idempotent on cached state: if `cache_root/{uuid}/{concrete_version}/`
    has `.comses_complete`, no network round-trips to /download/ happen and
    `cached=True` is returned.

    Raises `ComsesError` (or a subclass) on any failure. On size/safety
    failure, no cache directory is created.
    """
    resolved = await client.resolve_latest(identifier, version)

    final_dir = cache_root / identifier / resolved
    if is_cache_trusted(final_dir):
        return _inspect_extracted(
            identifier=identifier,
            resolved_version=resolved,
            extracted_path=final_dir,
            cached=True,
            title=None,
            license_name=None,
        )

    # Fetch release + codebase metadata for title/license + the correct
    # download URL. `submittedPackage` is NOT a reliable signal — real COMSES
    # returns null for it on most releases even when /download/ serves a real
    # zip. And the /download/ endpoint 404s on UUID paths; it requires the
    # numeric codebase id from the release's `absoluteUrl`. Rely on the
    # release response for both.
    title: str | None = None
    license_name: str | None = None
    download_url: str | None = None
    try:
        rel = await client.get_release(identifier, resolved)
        license_name = (rel.get("license") or {}).get("name")
        abs_url = rel.get("absoluteUrl")
        if isinstance(abs_url, str) and abs_url.startswith("/"):
            download_url = f"{client._base_url}{abs_url.rstrip('/')}/download/"
    except ComsesError:
        pass
    try:
        cb = await client.get_codebase(identifier)
        title = cb.get("title")
    except ComsesError:
        pass

    # HEAD screen: refuse obvious oversize before streaming.
    try:
        content_length, _ = await client.head_download(
            identifier, resolved, url=download_url
        )
    except ComsesHTTPError:
        content_length = None  # HEAD may not be supported; defer to stream cap.
    if content_length is not None and content_length > max_bytes:
        raise ComsesHTTPError(
            f"Archive is {content_length} bytes, exceeds cap of {max_bytes}. "
            "Increase max_mb or COMSES_MAX_DOWNLOAD_MB if you really want it."
        )

    # Stream to a unique temp file; then safe-extract.
    tmp_root = cache_root / ".tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp_zip = tmp_root / f"{identifier}-{resolved}-{os.getpid()}.zip"
    try:
        await client.stream_download(
            identifier, resolved, tmp_zip, max_bytes=max_bytes, url=download_url
        )
        safe_extract_zip(
            tmp_zip,
            final_dir,
            max_bytes=max_bytes,
            tmp_root=tmp_root,
        )
    finally:
        try:
            tmp_zip.unlink(missing_ok=True)
        except OSError:
            pass

    return _inspect_extracted(
        identifier=identifier,
        resolved_version=resolved,
        extracted_path=final_dir,
        cached=False,
        title=title,
        license_name=license_name,
    )


def _inspect_extracted(
    *,
    identifier: str,
    resolved_version: str,
    extracted_path: Path,
    cached: bool,
    title: str | None,
    license_name: str | None,
) -> DownloadOutcome:
    """Walk the extracted directory and build a DownloadOutcome."""
    language = detect_language(extracted_path)
    netlogo = find_netlogo_files(extracted_path)
    selected = select_netlogo_file(netlogo, extracted_path)
    code = find_code_files(extracted_path)
    odd = find_odd_doc(extracted_path)
    odd_bin = find_odd_doc_binary(extracted_path)
    return DownloadOutcome(
        identifier=identifier,
        resolved_version=resolved_version,
        extracted_path=extracted_path,
        cached=cached,
        language=language,
        netlogo_files=netlogo,
        selected_netlogo_file=selected,
        code_files=code,
        odd_doc=odd,
        odd_doc_binary=odd_bin,
        license_name=license_name,
        title=title,
    )


def find_code_files(extracted_dir: Path) -> list[Path]:
    """Plausible source files (one level deep under code/, or same at root)."""
    code_exts = (".nlogo", ".nlogox", ".py", ".r", ".R", ".jl", ".java")
    code_dir = extracted_dir / "code"
    root = code_dir if code_dir.is_dir() else extracted_dir
    found = [p for p in root.rglob("*") if p.is_file() and p.suffix in code_exts]
    found.sort(key=lambda p: p.relative_to(extracted_dir).as_posix())
    return found
