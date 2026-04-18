"""Tests for the CoMSES Net integration — mocked HTTP, no network, no JVM."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from netlogo_mcp import comses

FIXTURES = Path(__file__).parent / "fixtures" / "comses"


# ── Fixture loaders ───────────────────────────────────────────────────────────


def _fx(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _make_client(handler) -> comses.ComsesClient:
    """Build a ComsesClient whose underlying httpx uses the given handler."""
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        transport=transport, base_url=comses.BASE_URL, follow_redirects=True
    )
    return comses.ComsesClient(client=http)


# ── API client: search + metadata ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_builds_correct_url_and_returns_json():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/codebases/"
        assert request.url.params.get("format") == "json"
        assert request.url.params.get("query") == "predator-prey"
        assert request.url.params.get("page") == "2"
        return httpx.Response(200, json=_fx("search_result.json"))

    async with _make_client(handler) as client:
        data = await client.search(query="predator-prey", page=2)

    assert data["count"] == 54
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_search_without_query_omits_query_param():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "query" not in dict(request.url.params)
        return httpx.Response(200, json=_fx("search_result.json"))

    async with _make_client(handler) as client:
        await client.search()


@pytest.mark.asyncio
async def test_get_codebase_returns_title_and_releases():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/aaaaaaaa-1111-4aaa-8aaa-111111111111/")
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    async with _make_client(handler) as client:
        data = await client.get_codebase("aaaaaaaa-1111-4aaa-8aaa-111111111111")
    assert data["title"] == "Wolf Sheep Predation"
    assert len(data["releases"]) == 2


@pytest.mark.asyncio
async def test_get_release_returns_citation_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "releases/1.2.0" in request.url.path
        return httpx.Response(200, json=_fx("release_detail.json"))

    async with _make_client(handler) as client:
        rel = await client.get_release("aaaaaaaa-1111-4aaa-8aaa-111111111111", "1.2.0")
    assert "Wolf Sheep Predation" in rel["citationText"]


@pytest.mark.asyncio
async def test_resolve_latest_uses_latest_version_number():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    async with _make_client(handler) as client:
        assert await client.resolve_latest("xxx", "latest") == "1.2.0"


@pytest.mark.asyncio
async def test_resolve_latest_passthrough_for_concrete_version():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    async with _make_client(handler) as client:
        assert await client.resolve_latest("xxx", "1.0.0") == "1.0.0"
    assert calls == 0, "Concrete version must not trigger a codebase fetch"


# ── Retry policy ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retries_on_503_then_succeeds(monkeypatch):
    monkeypatch.setattr(comses.asyncio, "sleep", _fast_sleep)
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] < 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"count": 0, "results": []})

    async with _make_client(handler) as client:
        await client.search()
    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_does_not_retry_on_4xx():
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        return httpx.Response(404)

    async with _make_client(handler) as client:
        with pytest.raises(comses.ComsesHTTPError):
            await client.search()
    assert state["calls"] == 1


@pytest.mark.asyncio
async def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(comses.asyncio, "sleep", _fast_sleep)
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        return httpx.Response(503)

    async with _make_client(handler) as client:
        with pytest.raises(comses.ComsesHTTPError):
            await client.search()
    assert state["calls"] == comses.MAX_RETRIES + 1


@pytest.mark.asyncio
async def test_retries_on_network_error(monkeypatch):
    monkeypatch.setattr(comses.asyncio, "sleep", _fast_sleep)
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] < 2:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"count": 0, "results": []})

    async with _make_client(handler) as client:
        await client.search()
    assert state["calls"] == 2


@pytest.mark.asyncio
async def test_non_json_content_type_is_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html>interstitial</html>",
            headers={"Content-Type": "text/html"},
        )

    async with _make_client(handler) as client:
        with pytest.raises(comses.ComsesHTTPError):
            await client.search()


# ── MCP tools: search_comses + get_comses_model ───────────────────────────────


@pytest.mark.asyncio
async def test_search_comses_tool_returns_compact_json(monkeypatch):
    from netlogo_mcp import tools

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_fx("search_result.json"))

    _patch_client_factory(monkeypatch, handler)

    ctx = MagicMock()
    raw = await tools.search_comses(ctx, query="predator-prey", page=1)
    data = json.loads(raw)

    assert data["count"] == 54
    assert data["page"] == 1
    assert len(data["results"]) == 2
    first = data["results"][0]
    assert first["identifier"] == "aaaaaaaa-1111-4aaa-8aaa-111111111111"
    assert first["language"] == "NetLogo"
    assert first["isPeerReviewed"] is True
    assert first["downloads"] == 482
    assert "Jane Author" in first["authors"]


@pytest.mark.asyncio
async def test_search_comses_tool_rejects_invalid_page():
    from fastmcp.exceptions import ToolError

    from netlogo_mcp import tools

    ctx = MagicMock()
    with pytest.raises(ToolError):
        await tools.search_comses(ctx, query="x", page=0)


@pytest.mark.asyncio
async def test_get_comses_model_tool_includes_citation(monkeypatch):
    from netlogo_mcp import tools

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/releases/1.2.0" in path:
            return httpx.Response(200, json=_fx("release_detail.json"))
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    _patch_client_factory(monkeypatch, handler)

    ctx = MagicMock()
    raw = await tools.get_comses_model(
        ctx, identifier="aaaaaaaa-1111-4aaa-8aaa-111111111111"
    )
    data = json.loads(raw)

    assert data["title"] == "Wolf Sheep Predation"
    assert data["citation_text"].startswith("Author, J.")
    assert data["peerReviewed"] is True
    # Both releases should come through, with languages and licenses.
    assert len(data["releases"]) == 2
    latest = [r for r in data["releases"] if r["versionNumber"] == "1.2.0"][0]
    assert latest["language"] == "NetLogo"
    assert latest["license"] == "MIT"
    assert latest["downloadable"] is True


@pytest.mark.asyncio
async def test_get_comses_model_tool_survives_release_fetch_failure(monkeypatch):
    """If the /releases/<v>/ call fails, the codebase response still comes back."""
    from netlogo_mcp import tools

    def handler(request: httpx.Request) -> httpx.Response:
        if "/releases/" in request.url.path:
            return httpx.Response(500)
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    _patch_client_factory(monkeypatch, handler)

    ctx = MagicMock()
    raw = await tools.get_comses_model(
        ctx, identifier="aaaaaaaa-1111-4aaa-8aaa-111111111111"
    )
    data = json.loads(raw)
    # No citation (it lives on the release), but the codebase detail still surfaces.
    assert data["title"] == "Wolf Sheep Predation"
    assert data["citation_text"] == ""


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _fast_sleep(_seconds: float) -> None:
    """Replace asyncio.sleep so retry tests don't actually wait."""
    return None


def _patch_client_factory(monkeypatch, handler) -> None:
    """Patch ComsesClient() in tools.py to use our MockTransport."""
    from netlogo_mcp import tools

    original = comses.ComsesClient

    def factory(*args, **kwargs):
        transport = httpx.MockTransport(handler)
        http = httpx.AsyncClient(
            transport=transport,
            base_url=comses.BASE_URL,
            follow_redirects=True,
        )
        return original(client=http)

    monkeypatch.setattr(tools._comses, "ComsesClient", factory)


# ── Zip safety + extraction ──────────────────────────────────────────────────


def _make_zip(entries: dict[str, bytes]) -> bytes:
    """Build an in-memory zip with the given {path: bytes} entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_rejects_zip_with_path_traversal(tmp_path):
    """A zip with `../etc/passwd` must be rejected before extraction."""
    zip_bytes = _make_zip({"../etc/passwd": b"pwned"})
    archive = tmp_path / "evil.zip"
    archive.write_bytes(zip_bytes)

    with pytest.raises(comses.ComsesSafetyError):
        comses.safe_extract_zip(archive, tmp_path / "final", max_bytes=10_000_000)
    assert not (tmp_path / "final").exists()


def test_rejects_zip_with_absolute_path_member(tmp_path):
    # Drive letter path should be rejected too.
    zip_bytes = _make_zip({"C:/windows/evil.txt": b"x"})
    archive = tmp_path / "evil.zip"
    archive.write_bytes(zip_bytes)
    with pytest.raises(comses.ComsesSafetyError):
        comses.safe_extract_zip(archive, tmp_path / "final", max_bytes=10_000_000)


def test_rejects_zip_bomb_by_uncompressed_sum(tmp_path):
    """Uncompressed total > 2 × cap triggers bomb rejection."""
    # One 500-byte file, cap 100 bytes → 500 > 200.
    zip_bytes = _make_zip({"big.bin": b"A" * 500})
    archive = tmp_path / "bomb.zip"
    archive.write_bytes(zip_bytes)

    with pytest.raises(comses.ComsesSafetyError):
        comses.safe_extract_zip(archive, tmp_path / "final", max_bytes=100)


def test_safe_extract_happy_path_writes_marker(tmp_path):
    zip_bytes = _make_zip(
        {
            "codemeta.json": b'{"programmingLanguage": "NetLogo"}',
            "code/model.nlogo": b"to setup\nend\n",
            "docs/ODD.md": b"# ODD\n\nSome doc.\n",
        }
    )
    archive = tmp_path / "good.zip"
    archive.write_bytes(zip_bytes)
    final = tmp_path / "cache" / "xxx" / "1.0.0"

    out = comses.safe_extract_zip(archive, final, max_bytes=10_000_000)
    assert out == final
    assert (final / comses.COMPLETION_MARKER).is_file()
    assert (final / "code" / "model.nlogo").read_text().startswith("to setup")
    assert comses.is_cache_trusted(final)


def test_cleans_up_temp_on_extract_failure(tmp_path):
    zip_bytes = _make_zip({"../escape.txt": b"bad"})
    archive = tmp_path / "evil.zip"
    archive.write_bytes(zip_bytes)
    final = tmp_path / "final"

    with pytest.raises(comses.ComsesSafetyError):
        comses.safe_extract_zip(archive, final, max_bytes=10_000_000)

    # No tmp-*-final directory should linger.
    tmp_root = final.parent / ".tmp"
    if tmp_root.exists():
        leftover = list(tmp_root.iterdir())
        assert not leftover, f"Leftover temp dirs: {leftover}"


def test_is_cache_trusted_requires_marker(tmp_path):
    final = tmp_path / "dir"
    final.mkdir()
    assert not comses.is_cache_trusted(final)
    (final / comses.COMPLETION_MARKER).write_text("ok")
    assert comses.is_cache_trusted(final)


def test_race_orphan_without_marker_is_wiped_and_retried(tmp_path):
    """If final_dir exists but has no marker, safe_extract wipes and retries."""
    zip_bytes = _make_zip({"code/ok.nlogo": b"to setup\nend\n"})
    archive = tmp_path / "good.zip"
    archive.write_bytes(zip_bytes)
    final = tmp_path / "cache" / "xxx" / "1.0.0"
    final.mkdir(parents=True)
    # Leave a stale unmarked file — simulating a prior failed/interrupted writer.
    (final / "stale.txt").write_text("leftover")

    comses.safe_extract_zip(archive, final, max_bytes=10_000_000)
    assert (final / comses.COMPLETION_MARKER).is_file()
    assert not (final / "stale.txt").exists(), (
        "Orphan should have been wiped before retry"
    )


def test_race_peer_writer_with_marker_is_respected(tmp_path):
    zip_bytes = _make_zip({"code/ok.nlogo": b"to setup\nend\n"})
    archive = tmp_path / "good.zip"
    archive.write_bytes(zip_bytes)
    final = tmp_path / "cache" / "xxx" / "1.0.0"
    final.mkdir(parents=True)
    (final / "peer.txt").write_text("theirs")
    (final / comses.COMPLETION_MARKER).write_text("ok")

    comses.safe_extract_zip(archive, final, max_bytes=10_000_000)
    # Peer's files preserved.
    assert (final / "peer.txt").read_text() == "theirs"
    assert (final / comses.COMPLETION_MARKER).is_file()


# ── Post-extract inspection ──────────────────────────────────────────────────


def test_detect_language_from_codemeta(tmp_path):
    (tmp_path / "codemeta.json").write_text(
        json.dumps({"programmingLanguage": {"name": "Python"}})
    )
    assert comses.detect_language(tmp_path) == "Python"


def test_detect_language_fallback_by_extension(tmp_path):
    (tmp_path / "code").mkdir()
    (tmp_path / "code" / "a.nlogo").write_text("x")
    (tmp_path / "code" / "b.nlogo").write_text("x")
    assert comses.detect_language(tmp_path) == "NetLogo"


def test_select_netlogo_file_prefers_code_dir_and_nlogox(tmp_path):
    root = tmp_path
    (root / "top.nlogo").write_text("x")
    (root / "code").mkdir()
    (root / "code" / "old.nlogo").write_text("x")
    (root / "code" / "new.nlogox").write_text("x")
    files = comses.find_netlogo_files(root)
    selected = comses.select_netlogo_file(files, root)
    assert selected is not None
    assert selected.name == "new.nlogox"


def test_select_netlogo_file_lex_largest_tiebreaker(tmp_path):
    root = tmp_path
    (root / "code").mkdir()
    # Two .nlogox files, lex ordering picks the "larger" one.
    (root / "code" / "WolfSheep_2.0.nlogox").write_text("x")
    (root / "code" / "WolfSheep_3.0.nlogox").write_text("x")
    files = comses.find_netlogo_files(root)
    selected = comses.select_netlogo_file(files, root)
    assert selected is not None and selected.name == "WolfSheep_3.0.nlogox"


def test_select_netlogo_file_none_when_empty(tmp_path):
    assert comses.select_netlogo_file([], tmp_path) is None


def test_find_odd_doc_prefers_odd_then_readme(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ODD.md").write_text("odd")
    (tmp_path / "README.md").write_text("readme")
    found = comses.find_odd_doc(tmp_path)
    assert found is not None and found.name == "ODD.md"


# ── High-level download_release + MCP tool ───────────────────────────────────


@pytest.mark.asyncio
async def test_download_release_uses_cache_when_marker_present(tmp_path):
    """If the cache dir already has the marker, no HTTP call is made."""
    identifier = "abc"
    version = "1.0.0"
    cache_root = tmp_path / "cache"
    final = cache_root / identifier / version
    final.mkdir(parents=True)
    (final / "code").mkdir()
    (final / "code" / "model.nlogo").write_text("to setup\nend\n")
    (final / comses.COMPLETION_MARKER).write_text("ok")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(
            f"No HTTP call expected when cache is warm; got {request.url}"
        )

    async with _make_client(handler) as client:
        outcome = await comses.download_release(
            client, identifier, version, cache_root=cache_root, max_bytes=10_000_000
        )

    assert outcome.cached is True
    assert outcome.resolved_version == version
    assert outcome.extracted_path == final
    assert outcome.selected_netlogo_file is not None
    assert outcome.selected_netlogo_file.name == "model.nlogo"


@pytest.mark.asyncio
async def test_download_release_resolves_latest_and_extracts(tmp_path):
    identifier = "aaaaaaaa-1111-4aaa-8aaa-111111111111"
    cache_root = tmp_path / "cache"
    archive_bytes = _make_zip(
        {
            "codemeta.json": b'{"programmingLanguage": "NetLogo"}',
            "code/WolfSheep.nlogo": b"to setup\nend\nto-report population\n  report 1\nend\n",
            "docs/ODD.md": b"# ODD\n",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p.endswith(f"/codebases/{identifier}/") and request.method == "GET":
            return httpx.Response(200, json=_fx("codebase_detail.json"))
        if "/releases/1.2.0/download/" in p and request.method == "HEAD":
            return httpx.Response(
                200,
                headers={
                    "Content-Length": str(len(archive_bytes)),
                    "Content-Type": "application/zip",
                },
            )
        if "/releases/1.2.0/download/" in p and request.method == "GET":
            return httpx.Response(
                200,
                content=archive_bytes,
                headers={"Content-Type": "application/zip"},
            )
        if "/releases/1.2.0/" in p:
            return httpx.Response(200, json=_fx("release_detail.json"))
        raise AssertionError(f"Unexpected request: {request.method} {p}")

    async with _make_client(handler) as client:
        outcome = await comses.download_release(
            client,
            identifier,
            "latest",
            cache_root=cache_root,
            max_bytes=10_000_000,
        )

    assert outcome.cached is False
    assert outcome.resolved_version == "1.2.0"
    assert "latest" not in str(outcome.extracted_path)
    assert outcome.language == "NetLogo"
    assert outcome.selected_netlogo_file is not None
    assert outcome.selected_netlogo_file.name == "WolfSheep.nlogo"
    assert outcome.odd_doc is not None and outcome.odd_doc.name == "ODD.md"
    assert outcome.license_name == "MIT"
    assert outcome.title == "Wolf Sheep Predation"
    # Second call is a cache hit.
    async with _make_client(
        lambda r: httpx.Response(200, json=_fx("codebase_detail.json"))
    ) as client:
        again = await comses.download_release(
            client, identifier, "1.2.0", cache_root=cache_root, max_bytes=10_000_000
        )
    assert again.cached is True


@pytest.mark.asyncio
async def test_download_release_refuses_oversize_via_head(tmp_path):
    identifier = "abc"

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if request.method == "HEAD":
            return httpx.Response(
                200,
                headers={
                    "Content-Length": str(100_000_000),
                    "Content-Type": "application/zip",
                },
            )
        if "/releases/" in p:
            return httpx.Response(200, json=_fx("release_detail.json"))
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    async with _make_client(handler) as client:
        with pytest.raises(comses.ComsesHTTPError, match="exceeds cap"):
            await comses.download_release(
                client,
                identifier,
                "1.2.0",
                cache_root=tmp_path / "cache",
                max_bytes=1_000_000,
            )


@pytest.mark.asyncio
async def test_download_release_refuses_non_zip_response(tmp_path):
    """An HTML interstitial response must fail hard, not corrupt the cache."""
    identifier = "abc"

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if request.method == "HEAD":
            return httpx.Response(200, headers={"Content-Type": "application/zip"})
        if "/releases/" in p and request.method == "GET" and "/download/" in p:
            return httpx.Response(
                200,
                content=b"<html>login form</html>",
                headers={"Content-Type": "text/html"},
            )
        if "/releases/" in p:
            return httpx.Response(200, json=_fx("release_detail.json"))
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    async with _make_client(handler) as client:
        with pytest.raises(comses.ComsesHTTPError, match="zip"):
            await comses.download_release(
                client,
                identifier,
                "1.2.0",
                cache_root=tmp_path / "cache",
                max_bytes=10_000_000,
            )
    # No cache dir should exist.
    assert not (tmp_path / "cache" / identifier / "1.2.0").exists()


@pytest.mark.asyncio
async def test_download_release_tolerates_null_submitted_package(tmp_path):
    """Real COMSES returns submittedPackage: null even when /download/ works.

    The authoritative gate is HEAD + stream content-type, not this field.
    """
    identifier = "abc"
    empty_release = dict(_fx("release_detail.json"))
    empty_release["submittedPackage"] = None
    archive_bytes = _make_zip({"code/ok.nlogo": b"to setup\nend\n"})

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if request.method == "HEAD":
            return httpx.Response(200, headers={"Content-Type": "application/zip"})
        if "/download/" in p:
            return httpx.Response(
                200,
                content=archive_bytes,
                headers={"Content-Type": "application/zip"},
            )
        if "/releases/" in p:
            return httpx.Response(200, json=empty_release)
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    async with _make_client(handler) as client:
        outcome = await comses.download_release(
            client,
            identifier,
            "1.2.0",
            cache_root=tmp_path / "cache",
            max_bytes=10_000_000,
        )
    assert outcome.cached is False
    assert outcome.selected_netlogo_file is not None


@pytest.mark.asyncio
async def test_download_comses_model_tool_returns_expected_shape(monkeypatch, tmp_path):
    from netlogo_mcp import tools

    identifier = "aaaaaaaa-1111-4aaa-8aaa-111111111111"
    archive_bytes = _make_zip(
        {
            "codemeta.json": b'{"programmingLanguage": "NetLogo"}',
            "code/WolfSheep_3.0.nlogox": b"to setup\nend\n",
            "code/WolfSheep_2.0.nlogo": b"to setup\nend\n",
            "docs/ODD.md": b"# ODD",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if request.method == "HEAD":
            return httpx.Response(200, headers={"Content-Type": "application/zip"})
        if "/download/" in p:
            return httpx.Response(
                200, content=archive_bytes, headers={"Content-Type": "application/zip"}
            )
        if "/releases/" in p:
            return httpx.Response(200, json=_fx("release_detail.json"))
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    _patch_client_factory(monkeypatch, handler)
    monkeypatch.setattr(tools, "get_comses_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(tools, "get_comses_max_download_mb", lambda: 10.0)

    ctx = MagicMock()
    raw = await tools.download_comses_model(
        ctx, identifier=identifier, version="latest"
    )
    data = json.loads(raw)

    assert data["resolved_version"] == "1.2.0"
    assert data["language"] == "NetLogo"
    assert data["cached"] is False
    assert data["loaded_netlogo_file"] == "code/WolfSheep_3.0.nlogox"
    assert sorted(data["all_netlogo_files"]) == [
        "code/WolfSheep_2.0.nlogo",
        "code/WolfSheep_3.0.nlogox",
    ]
    assert data["odd_doc"] == "docs/ODD.md"
    assert data["license"] == "MIT"
    assert "latest" not in data["extracted_path"]


# ── open_comses_model tool ───────────────────────────────────────────────────


def _prime_cache(
    cache_root: Path, identifier: str, version: str, files: dict[str, bytes]
) -> Path:
    """Write a fully-marked cache directory so read/open tools can skip download."""
    final = cache_root / identifier / version
    final.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        path = final / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (final / comses.COMPLETION_MARKER).write_text("ok", encoding="utf-8")
    return final


@pytest.mark.asyncio
async def test_open_comses_model_loads_netlogo_when_cached(
    monkeypatch, tmp_path, mock_context, mock_nl
):
    from netlogo_mcp import tools

    identifier = "abc"
    version = "1.0.0"
    cache_root = tmp_path / "cache"
    _prime_cache(
        cache_root,
        identifier,
        version,
        {
            "code/Wolf.nlogo": b"to setup\nend\nto go\nend\n",
            "codemeta.json": b'{"programmingLanguage": "NetLogo"}',
            "docs/ODD.md": b"# ODD",
        },
    )

    monkeypatch.setattr(tools, "get_comses_cache_dir", lambda: cache_root)

    # No HTTP should happen at all on a warm cache + concrete version.
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request: {request.url}")

    _patch_client_factory(monkeypatch, handler)

    raw = await tools.open_comses_model(
        mock_context, identifier=identifier, version=version
    )
    data = json.loads(raw)

    assert data["status"] == "loaded_netlogo"
    assert data["resolved_version"] == version
    assert data["cached"] is True
    assert data["loaded_netlogo_file"] == "code/Wolf.nlogo"
    assert mock_nl._model_loaded is True
    assert "Pin resolved_version" in data["message"]


@pytest.mark.asyncio
async def test_open_comses_model_non_netlogo_returns_structured_json(
    monkeypatch, tmp_path, mock_context, mock_nl
):
    from netlogo_mcp import tools

    identifier = "abc"
    version = "1.0.0"
    cache_root = tmp_path / "cache"
    _prime_cache(
        cache_root,
        identifier,
        version,
        {
            "code/model.py": b"# python\n",
            "codemeta.json": b'{"programmingLanguage": {"name": "Python"}}',
            "docs/ODD.md": b"# ODD",
        },
    )

    monkeypatch.setattr(tools, "get_comses_cache_dir", lambda: cache_root)
    _patch_client_factory(
        monkeypatch, lambda r: (_ for _ in ()).throw(AssertionError("no HTTP expected"))
    )

    raw = await tools.open_comses_model(
        mock_context, identifier=identifier, version=version
    )
    data = json.loads(raw)

    assert data["status"] == "not_runnable_in_netlogo"
    assert data["language"] == "Python"
    assert data["loaded_netlogo_file"] is None
    assert mock_nl._model_loaded is False
    assert "not automatic" in data["message"]


# ── read_comses_files tool ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_comses_files_priority_odd_first_then_nlogo(
    monkeypatch, tmp_path, mock_context
):
    from netlogo_mcp import tools

    identifier = "abc"
    version = "1.0.0"
    cache_root = tmp_path / "cache"
    _prime_cache(
        cache_root,
        identifier,
        version,
        {
            "docs/ODD.md": b"# ODD\nThis is the ODD doc.\n",
            "code/Wolf.nlogo": b"to setup\nend\n",
            "code/helper.py": b"# python helper\n",
        },
    )
    monkeypatch.setattr(tools, "get_comses_cache_dir", lambda: cache_root)

    raw = await tools.read_comses_files(
        mock_context, identifier=identifier, version=version
    )
    data = json.loads(raw)

    assert data["resolved_version"] == version
    keys = list(data["files"].keys())
    # ODD first, then .nlogo, then helper.py.
    assert keys.index("docs/ODD.md") < keys.index("code/Wolf.nlogo")
    assert keys.index("code/Wolf.nlogo") < keys.index("code/helper.py")


@pytest.mark.asyncio
async def test_read_comses_files_respects_byte_cap_and_truncates(
    monkeypatch, tmp_path, mock_context
):
    from netlogo_mcp import tools

    identifier = "abc"
    version = "1.0.0"
    cache_root = tmp_path / "cache"
    # One ODD doc small, one big .nlogo that will be truncated.
    big = ("line\n" * 1000).encode("utf-8")  # 5000 bytes
    _prime_cache(
        cache_root,
        identifier,
        version,
        {"docs/ODD.md": b"short\n", "code/big.nlogo": big},
    )
    monkeypatch.setattr(tools, "get_comses_cache_dir", lambda: cache_root)

    raw = await tools.read_comses_files(
        mock_context, identifier=identifier, version=version, max_total_bytes=500
    )
    data = json.loads(raw)

    odd = data["files"]["docs/ODD.md"]
    big_entry = data["files"]["code/big.nlogo"]
    assert odd["truncated"] is False
    assert big_entry["truncated"] is True
    assert big_entry["returned_size"] < big_entry["full_size"]
    assert data["any_truncated"] is True
    # Truncation must land on a line boundary.
    assert big_entry["content"].endswith("\n")


@pytest.mark.asyncio
async def test_read_comses_files_omits_files_with_reasons(
    monkeypatch, tmp_path, mock_context
):
    from netlogo_mcp import tools

    identifier = "abc"
    version = "1.0.0"
    cache_root = tmp_path / "cache"
    _prime_cache(
        cache_root,
        identifier,
        version,
        {
            "data/input.csv": b"col\n1\n",
            "code/Wolf.nlogo": b"to setup\nend\n",
        },
    )
    monkeypatch.setattr(tools, "get_comses_cache_dir", lambda: cache_root)

    raw = await tools.read_comses_files(
        mock_context, identifier=identifier, version=version
    )
    data = json.loads(raw)
    assert "data/input.csv" in data["omitted_reason_by_file"]
    assert data["omitted_reason_by_file"]["data/input.csv"] == "extension_not_in_filter"


@pytest.mark.asyncio
async def test_read_comses_files_errors_when_cache_missing(
    monkeypatch, tmp_path, mock_context
):
    from fastmcp.exceptions import ToolError

    from netlogo_mcp import tools

    monkeypatch.setattr(tools, "get_comses_cache_dir", lambda: tmp_path / "cache")
    with pytest.raises(ToolError, match="missing or incomplete"):
        await tools.read_comses_files(
            mock_context, identifier="unknown", version="1.0.0"
        )


@pytest.mark.asyncio
async def test_read_comses_files_zero_match_returns_empty_files(
    monkeypatch, tmp_path, mock_context
):
    from netlogo_mcp import tools

    identifier = "abc"
    version = "1.0.0"
    cache_root = tmp_path / "cache"
    _prime_cache(cache_root, identifier, version, {"data/input.csv": b"x"})
    monkeypatch.setattr(tools, "get_comses_cache_dir", lambda: cache_root)

    raw = await tools.read_comses_files(
        mock_context,
        identifier=identifier,
        version=version,
        extensions=[".nlogo"],
    )
    data = json.loads(raw)
    assert data["files"] == {}
    assert data["total_returned_bytes"] == 0
    assert data["any_truncated"] is False
    assert "data/input.csv" in data["omitted_files"]


@pytest.mark.asyncio
async def test_read_comses_files_resolves_latest_via_http(
    monkeypatch, tmp_path, mock_context
):
    from netlogo_mcp import tools

    identifier = "aaaaaaaa-1111-4aaa-8aaa-111111111111"
    cache_root = tmp_path / "cache"
    # Prime cache at resolved 1.2.0 (from fixture).
    _prime_cache(
        cache_root,
        identifier,
        "1.2.0",
        {"docs/ODD.md": b"# ODD\n"},
    )
    monkeypatch.setattr(tools, "get_comses_cache_dir", lambda: cache_root)

    def handler(request: httpx.Request) -> httpx.Response:
        # Only get_codebase (for latest resolution) should be called.
        assert request.url.path.endswith(f"/codebases/{identifier}/")
        return httpx.Response(200, json=_fx("codebase_detail.json"))

    _patch_client_factory(monkeypatch, handler)

    raw = await tools.read_comses_files(
        mock_context, identifier=identifier, version="latest"
    )
    data = json.loads(raw)
    assert data["resolved_version"] == "1.2.0"
    assert "docs/ODD.md" in data["files"]


# ── explore_comses prompt ────────────────────────────────────────────────────


def test_explore_comses_prompt_has_required_rules():
    """The prompt must encode the rules that keep the flow researcher-safe."""
    from netlogo_mcp.prompts import explore_comses

    msgs = explore_comses("rumor spreading")
    assert len(msgs) == 1
    body = msgs[0].content.text

    # Topic is interpolated.
    assert "rumor spreading" in body
    # Pin-the-version rule.
    assert "resolved_version" in body
    assert 'Never pass "latest" again' in body or 'Never pass "latest"' in body
    # Both extensions when reading NetLogo source.
    assert ".nlogo" in body and ".nlogox" in body
    # Runtime-error stop rule.
    assert (
        "do NOT guess alternates" in body or "do not guess alternates" in body.lower()
    )
    # Stop-and-ask fallback and no auto-translation.
    assert "Stop-and-ask" in body or "stop-and-ask" in body.lower()
    assert "Do NOT auto-translate" in body or "not auto-translate" in body.lower()


# ── Language hint heuristic (real COMSES search results omit releaseLanguages)


def test_language_hint_from_title_and_description():
    from netlogo_mcp.tools import _language_hint_from_text

    assert _language_hint_from_text({"title": "Wolf Sheep Netlogo Model"}) == "NetLogo"
    assert (
        _language_hint_from_text({"description": "Implemented in Python using Mesa."})
        == "Python"
    )
    assert _language_hint_from_text({"tags": [{"name": "Repast"}]}) == "Repast"
    assert _language_hint_from_text({"title": "ecology of wolves"}) is None


@pytest.mark.asyncio
async def test_search_comses_falls_back_to_heuristic_when_release_langs_absent(
    monkeypatch,
):
    """Real COMSES search results don't include releaseLanguages.

    The compact response must still get a language when the text mentions one.
    """
    from netlogo_mcp import tools

    stripped = json.loads(json.dumps(_fx("search_result.json")))
    # Strip releaseLanguages to simulate real API.
    for r in stripped["results"]:
        for rel in r.get("releases") or []:
            rel["releaseLanguages"] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=stripped)

    _patch_client_factory(monkeypatch, handler)

    ctx = MagicMock()
    raw = await tools.search_comses(ctx, query="x", page=1)
    data = json.loads(raw)
    # "Wolf Sheep Predation" + "NetLogo" tag → picked up via heuristic.
    assert data["results"][0]["language"] == "NetLogo"
    # Second result has "Python" in tags + description.
    assert data["results"][1]["language"] == "Python"
