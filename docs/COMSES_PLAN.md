# COMSES Integration Plan

Research + design doc for extending NetLogo MCP with COMSES model library access.

Audience: future contributors, Serge/Jiaan (as demo material), my own implementation reference.

---

## Ship Philosophy

**Ship v1 in ~6 hours of focused work (1–2 evenings). Expand only when asked.**

Serge said trust is earned through delivery. A correct, narrowly-scoped v1 in his hands is more valuable than an ambitious v2 that leaks bugs. This plan is intentionally minimal and **resists scope creep** — notably, cross-language translation is not a main promise; it is an optional follow-up the user can ask for.

---

## 1. Goal

Enable NetLogo MCP to:
1. Search the CoMSES Net Computational Model Library
2. View model metadata including **citation-ready text** for use in papers
3. **Safely** download any model from COMSES to the local `models/` folder
4. Load NetLogo models directly
5. For non-NetLogo models, clearly identify the language and give the user path + file info for optional manual follow-up

**Pitch in one sentence:** *Search COMSES, inspect citation-ready metadata, download archives safely, and open NetLogo models directly. Non-NetLogo models are identified clearly, with optional manual follow-up.*

This fulfills Serge Stinckwich's direct request on 2026-04-17:
> "Would be nice if there an agent skills to explore existing ABM on COMSES or github"

**What this is not:** not a translation service, not a GitHub mirror, not a model runner for Python/R/etc. Cross-language translation is *possible* (the AI can be asked), but is explicitly **not** a v1 selling point.

---

## 2. Verified API Behavior

Base URL: `https://www.comses.net`

Every endpoint verified by live HTTP calls during research.

| Endpoint | Purpose | Returns | Notes |
|----------|---------|---------|-------|
| `GET /codebases/?format=json&page=N` | List all models (paginated, 10/page) | Paginated JSON | Works anonymously |
| `GET /codebases/?format=json&query=TERM` | Full-text search | Paginated JSON | 54 results for "predator-prey", 235 for "NetLogo" |
| `GET /codebases/?format=json&tags=TAG` | Filter by user tags | Paginated JSON | Tags are free-form strings, quality varies |
| `GET /codebases/{uuid}/?format=json` | Single model metadata | JSON | Title, authors, all releases |
| `GET /codebases/{uuid}/releases/{ver}/?format=json` | Release metadata | JSON | License, languages, platforms |
| `GET /codebases/{uuid}/releases/{ver}/download/` | Download archive | `application/zip` | Direct GET — no form required |
| `GET /programming-languages/?format=json` | Language catalog | List of `{id, name, url, ...}` | NetLogo id=19 |

### Pagination Shape

```json
{
  "isFirstPage": true,
  "isLastPage": false,
  "currentPage": 1,
  "numResults": 10,
  "count": 1270,
  "numPages": 127,
  "results": [ ... ]
}
```

### Key Fields on a Codebase (search result)

```
identifier, title, description, summarizedDescription
allContributors (with names, affiliations, ORCID)
tags (user-defined, free-form)
releases[] (with versionNumber, absoluteUrl, live)
latestVersionNumber, firstPublishedAt, lastPublishedOn
downloadCount, peerReviewed, doi
featuredImage, repositoryUrl
```

### Key Fields on a Release

```
license (SPDX with name + url)
platforms[] (e.g., NetLogo, numpy, pandas, NetLogo)
releaseLanguages[] (with programmingLanguage.id and .name — THIS is authoritative for language)
programmingLanguageTags[] (additional user-specified tags)
documentation (URL to external docs, often null)
os, osDisplay (platform_independent / linux / etc.)
dependencies
citationText, outputDataUrl, doi
live (bool — does the model have a downloadable archive)
embargoEndDate (usually null)
reviewStatus
submittedPackage (null if nothing downloadable)
```

### Archive Structure (ZIP contents)

Observed across 5 real downloads — consistent pattern:

```
codemeta.json          # schema.org SoftwareSourceCode metadata
LICENSE                # Full license text
CITATION.cff           # Citation File Format
code/                  # Source code (.nlogo, .nlogox, .py, .R, etc.)
docs/                  # ODD documentation (varies — PDF / MD / TXT)
data/                  # Optional input data
results/               # Optional example output data
```

Real file names observed:
- `code/WolfSheep_3.0.nlogo` (NetLogo 6 format)
- `code/ABM-approach-to-anxiety-kapeller2020.nlogo`
- `docs/ODD_Protocol.md`, `docs/ODDprotocolStep9.pdf`, `docs/documentation-ABM-anxiety-to-approach-kapeller2020.txt`

---

## 3. Issues Discovered During Research (Ordered by Severity)

### High: Zip-slip and poisoned-cache risk in extraction

If we extract third-party ZIP archives directly into `models/comses/{uuid}/{version}/`, a malicious archive with `../` path traversal entries could write files outside the target directory. Worse: a partial download or interrupted extraction followed by "skip if target exists" caching could leave a corrupt directory that future runs trust.

Mitigation — **mandatory in v1**:

1. **Validate every zip member before extraction.** For each `ZipInfo.filename`:
   - Reject if it contains `..`, starts with `/`, or is an absolute path (Windows drive letters).
   - After `Path(target_dir, member_name).resolve()`, assert the result is still within `target_dir.resolve()` (use `Path.is_relative_to()`).
   - Reject any zip with a suspicious member.
2. **Atomic extract:** download to `temp_file.zip`, extract into `temp_dir/`, and only once extraction succeeds, `shutil.move(temp_dir, final_dir)`. Never extract directly into the cache path.
3. **Completion marker:** write a `.comses_complete` file inside `final_dir` after successful extraction. On reuse, only trust a cached directory if that marker is present. If not, wipe and redownload.
4. **Reject gigantic archives at extraction time too:** sum uncompressed sizes from `ZipInfo.file_size`; if total exceeds `2 × max_mb` (to catch zip bombs with high compression ratios), refuse.

### High: Some "live" models have no downloadable archive

Example: BHSPopDy (UUID `7facda08-dbef-4ceb-b069-17b3cd964cee`, v1.2.0)
- Metadata shows `live: True`, `submittedPackage: null`
- `/download/` returns **HTTP 404** with HTML body (not a zip)

Mitigation:
- Before downloading, check release metadata; if `submittedPackage` is null, warn the user.
- On download, check HTTP status AND `Content-Type`. If not `application/zip`, treat as failure.

### High: Archive size varies from 50KB to 70MB+

Samples observed:
- Typical NetLogo model: **56KB – 500KB**
- With data: **2 – 25MB**
- With GIS / large inputs: **70MB** (LogoClim)

Mitigation (operational, stream-time enforcement):
- Default download cap: **50MB** (configurable via env var `COMSES_MAX_DOWNLOAD_MB`).
- `HEAD` request first as a quick screen — if `Content-Length` is present and exceeds cap, refuse before downloading.
- **`HEAD` is not authoritative** — some responses omit `Content-Length` or lie about it. The stream must enforce the cap in real time: count bytes as they arrive; if the total exceeds cap mid-stream, abort the connection, delete the partial file.
- Stream to a temp file on disk (never buffer in memory).

### Medium: Language tag filter (`programming_languages=19`) returns 0 results

The tag filter does not map to internal language IDs. Must either:
- Use text query `query=NetLogo` (returns 235 — matches models with "NetLogo" in text)
- Filter client-side after fetch by inspecting `release.releaseLanguages`

Mitigation:
- `search_comses` does not accept a `language` filter — we explicitly do not hide results by language (see Section 4.1).
- After fetching a candidate, the server reads `release.releaseLanguages` and exposes a `language` field on each result so the AI and user can route correctly.

### Medium: User-defined tags are free-form and inconsistent

One model has tags `["ODD protocol", "Malaria", "kenya"]`, another has `[]`.

Mitigation:
- Don't rely on tags for primary filtering.
- Use the `query` field + `tags` field for best coverage.
- Expose both to the user.

### Medium: Latency is ~2s per API call

Sequential 10 calls average 2,000–2,500ms each. Reasonable but noticeable.

Mitigation:
- `run_simulation`-style tool responses are already "long-form" to Claude users.
- Cache a lightweight result list in-memory for the life of one session (search then view detail shouldn't re-search).
- Document expected latency in each tool's docstring.

### Low: Cloudflare / transient network errors

One of three consecutive rapid downloads returned an HTML error page once, then succeeded on retry.

Mitigation (explicit retry policy):
- Retry only on: HTTP `502`, `503`, `504`, network timeout, `httpx.ConnectError`, `httpx.ReadError`.
- **Do NOT retry on:** `4xx` (client error — indicates bug or missing data), `200` with unexpected `Content-Type` (indicates we got an interstitial — retrying won't help).
- Max 2 retries. Exponential backoff: 1s, then 2s.
- Log every retry attempt with reason.
- Implemented explicitly in `comses.py` — not delegated to a library default.

### Low: Truncated UUIDs in some UI contexts

UUIDs in the table of results are short-form in some rendering. In the JSON they are full-form.

Mitigation:
- Always use full UUID (from `identifier` field) when calling downstream APIs.

### Low: Download endpoint sometimes needs no auth, sometimes shows an interstitial

The interstitial HTML with `request_download` form only appears when there's a separate rule (e.g., redirects, Cloudflare challenge). Direct GET to `/download/` works >95% of the time.

Mitigation:
- Do a direct GET. If it fails, do not attempt to simulate the form submission (requires user affiliation data we don't have / shouldn't fake).
- Surface a friendly error: "Download requires filling out a form on comses.net — please visit {url} to download manually."

### Low: ODD documentation format is inconsistent (PDF / MD / TXT)

Some models have it, some don't. File naming varies.

Mitigation:
- After extraction, look for common patterns in `docs/`: `ODD*.md`, `ODD*.pdf`, `documentation*.txt`, `README*.md`.
- Record the path in the `open_comses_model` / `download_comses_model` result so the AI can read it via `read_comses_files` (text formats only — PDFs are out of scope for v1).

### Low: Models may not be loadable by NetLogo MCP

If the model is Python (Mesa), R, Julia, or Java, it's not runnable through our NetLogo bridge.

Mitigation:
- Before attempting `open_model`, inspect `releaseLanguages` field.
- If not NetLogo, return the download path and tell the user the language and that they'll need a different tool to run it.

---

## 4. Tool Design (v1)

**Five MCP tools, one prompt.** All async, use `httpx.AsyncClient`. No filtering that hides results from the user — language info is surfaced per result so AI/user can decide. File access works on every MCP client (not just those with filesystem tools).

### 4.1 `search_comses`

```python
@mcp.tool()
async def search_comses(
    ctx: Context,
    query: str = "",
    page: int = 1,
) -> str:
    """Search the CoMSES Net computational model library.

    Args:
        query: Free-text search (title, description, authors, tags).
               Leave empty to browse all models.
        page: Results page (1-indexed, 10 per page).

    Returns JSON: {count, page, numPages, results: [{identifier, title,
    description, authors, latestVersion, tags, language, isPeerReviewed,
    downloads}]}

    Note: Returns all matches regardless of language. The `language` field on
    each result (inferred from the latest release) lets the AI filter or
    route to translation.
    """
```

Shape returned to the LLM: compact JSON with only the fields Claude needs. **No `netlogo_only` filter** — we trust the AI and user to pick the right model.

### 4.2 `get_comses_model`

```python
@mcp.tool()
async def get_comses_model(ctx: Context, identifier: str) -> str:
    """Get detailed metadata for a specific COMSES model.

    Args:
        identifier: Full UUID (from search_comses results).

    Returns JSON with: title, description, all authors (names/ORCID),
    all releases (version, languages, license, downloadable flag),
    tags, DOI, repository URL, download counts, and a ready-to-use
    `citation_text` that researchers can drop into papers.
    """
```

**Citation field is important.** COMSES exposes `citationText` on release metadata. Researchers always need to cite. Including this makes the tool feel native to their workflow.

### 4.3 `download_comses_model`

Standalone download tool for callers who explicitly want "fetch but don't open."

```python
@mcp.tool()
async def download_comses_model(
    ctx: Context,
    identifier: str,
    version: str = "latest",
    max_mb: float = 50.0,
) -> str:
    """Safely download and extract a COMSES model archive.

    Args:
        identifier: Full model UUID.
        version: Version string (e.g. '1.0.0') or 'latest'.
        max_mb: Max download size in MB. Enforced at stream time, not just HEAD.

    Returns JSON: {
      extracted_path, language, netlogo_files, code_files, odd_doc,
      license, version, cached (bool — true if we used an existing cached dir)
    }
    """
```

Implementation details (see sections 3 and 4.6 for full requirements):
- **Resolve `"latest"` to a concrete version BEFORE computing any cache path** (see 4.6).
- HEAD screen → refuse if `Content-Length` known-exceeds cap.
- Stream download to `temp_file.zip` under `models/comses/.tmp/`, enforce byte cap mid-stream.
- Validate every zip member path (reject traversal).
- Check sum of uncompressed sizes; refuse zip bombs (> `2 × max_mb`).
- Extract to `temp_dir/`, then `shutil.move(temp_dir, models/comses/{uuid}/{concrete_version}/)` atomically.
- Write `.comses_complete` marker. Future calls check this marker before reusing cache.
- Detect language from `codemeta.json` (`programmingLanguage` field) or from extension scan fallback.

### 4.4 `open_comses_model` (cache-aware; main entry point for AI flows)

```python
@mcp.tool()
async def open_comses_model(
    ctx: Context,
    identifier: str,
    version: str = "latest",
    max_mb: float = 50.0,
) -> str:
    """Get a COMSES model ready to use.

    - If cached locally (marker present), skip download.
    - Otherwise download + extract (same logic as download_comses_model).
    - If the model is NetLogo, load it into the NetLogo workspace.
    - If not NetLogo, do NOT load; return structured info for manual follow-up.

    Args:
        identifier: Full model UUID.
        version: Version string or 'latest'.
        max_mb: Max download size cap.

    Returns:
      - NetLogo case: "Loaded NetLogo model: <filename> (cached)" or "(downloaded)"
      - Non-NetLogo case: structured JSON, see below.
    """
```

This is the **single entry point** for "I want this model ready to use." It subsumes downloading. Users who want to download without opening can call `download_comses_model` directly; most AI flows will call this tool.

#### Selecting which NetLogo file to load (when the archive has more than one)

Some COMSES archives contain multiple `.nlogo` / `.nlogox` files (e.g.,
different variants of a model, or the authors shipped both a v1 and v2).
`open_comses_model` picks deterministically:

1. If exactly one `.nlogo` or `.nlogox` file exists, use it.
2. Otherwise, prefer files under `code/` over any other directory.
3. Within that, prefer `.nlogox` over `.nlogo` (newer format).
4. Within that, pick the lexicographically largest **relative path** as a
   pure tie-breaker. This is *not* a semver sort — `v10` lex-orders before
   `v2`, and `1.10` before `1.9`. The rule exists only to make the choice
   reproducible across runs; it does not claim to pick the "newest" file.
   When multiple candidates exist, the AI should surface them to the user
   rather than trusting the tie-breaker as a version-aware pick.
5. The response includes `all_netlogo_files` listing every candidate and
   `loaded_netlogo_file` saying which one we picked, so the AI can offer
   the user a chance to switch.

The non-NetLogo response shape:

```json
{
  "status": "not_runnable_in_netlogo",
  "language": "Python (Mesa)",
  "title": "SIR Epidemic Model",
  "extracted_path": "models/comses/{uuid}/{resolved_version}/",
  "code_files": ["code/model.py", "code/agents.py"],
  "odd_doc": "docs/ODD.md",
  "message": "This model is in Python, not NetLogo. The source is saved locally. You can read it with the read_comses_files tool if you want to understand or adapt it. Translating it to NetLogo is possible but not automatic — ask explicitly if that's what you want."
}
```

The `message` is deliberately lower-key than the earlier "Ask the user if they want me to convert it" framing. **Translation is not promoted as a feature here.** It's available via a separate user request.

### 4.5 `read_comses_files` (in v1 — enables cross-client file access)

```python
@mcp.tool()
async def read_comses_files(
    ctx: Context,
    identifier: str,
    version: str = "latest",
    extensions: list[str] = [".nlogo", ".nlogox", ".py", ".r", ".R", ".java", ".jl", ".md", ".txt"],
    max_total_bytes: int = 200_000,
) -> str:
    """Return contents of source + documentation files from a downloaded COMSES model.

    The model must already be downloaded. If the cache is absent, the tool
    returns an error telling the AI to call download_comses_model or
    open_comses_model first.

    Works on every MCP client regardless of filesystem tool availability.

    Args:
        identifier: Full model UUID.
        version: Version string or 'latest'. Resolved to concrete version
                 for cache lookup.
        extensions: File types to include. Default covers code + docs.
        max_total_bytes: Cap total returned content (default 200KB).

    Returns JSON — see contract below.
    """
```

#### Return contract

```json
{
  "resolved_version": "1.2.0",
  "files": {
    "docs/ODD.md":        {"content": "...", "full_size": 18071, "returned_size": 18071, "truncated": false},
    "code/WolfSheep.nlogo": {"content": "...", "full_size": 57867, "returned_size": 50000, "truncated": true}
  },
  "omitted_files": ["results/checkpoint.json", "data/large_input.csv"],
  "omitted_reason_by_file": {
    "results/checkpoint.json": "extension_not_in_filter",
    "data/large_input.csv":   "byte_cap_reached"
  },
  "total_returned_bytes": 68071,
  "any_truncated": true
}
```

#### Priority ordering (deterministic)

Files are included in this priority, until the byte cap is hit:
1. ODD docs: `docs/ODD*`, `docs/odd*`, `docs/documentation*`, `docs/README*`, `README*`
2. NetLogo source: `**/*.nlogo`, `**/*.nlogox`
3. Other code in request-order of `extensions`: `.py`, `.r`, `.R`, `.java`, `.jl`
4. Remaining `.md`, `.txt` outside `docs/`
5. Anything else matching `extensions` not yet included

If the byte cap is hit mid-file, that file's `content` is cut at a safe
boundary (prefer line end), `returned_size < full_size`, and `truncated: true`.
Files not even started are listed in `omitted_files` with reason
`"byte_cap_reached"`.

#### Zero-match case

If no files in the cache match `extensions`, return:

```json
{
  "resolved_version": "1.2.0",
  "files": {},
  "omitted_files": ["..."],
  "omitted_reason_by_file": {"...": "extension_not_in_filter"},
  "total_returned_bytes": 0,
  "any_truncated": false
}
```

The AI sees an empty `files` map plus the full `omitted_files` list and can
either widen `extensions` or report back to the user.

#### Text decoding policy

All file contents are decoded as **UTF-8 with `errors="replace"`**. This keeps
the contract simple: every included file returns a string. Binary or
mis-encoded content shows up as content with replacement characters, which is
strictly more useful than failing the whole call. Files matching `extensions`
are never silently dropped for decode reasons.

Why it's in v1 (not deferred): Claude Desktop has no filesystem tools, and
the existing `model_source` resource only handles flat filenames — not the
nested paths under `models/comses/{uuid}/{version}/docs/` or `/code/`. Without
`read_comses_files`, the happy-path flow doesn't actually work across clients.

### Single Prompt: `explore_comses` (NetLogo-first)

```python
@mcp.prompt()
def explore_comses(topic: str) -> list[Message]:
    """Search COMSES for a topic, pick the best NetLogo match, download, load,
    and run a short baseline simulation.

    - Preferentially picks peer-reviewed NetLogo models.
    - Inspects the model's NetLogo source to find real procedure and reporter
      names before running (does not assume 'setup' / 'go' exist).
    - For non-NetLogo matches, reports language + citation + ODD path and
      stops — does not auto-translate. Translation is available if the user
      explicitly asks.
    """
```

The prompt instructs the AI to:
1. Search COMSES for models matching the topic; prefer peer-reviewed + NetLogo-tagged.
2. Show the user the top match with title, authors, description, **citation text**.
3. Call `open_comses_model`.
4. If the model is NetLogo (happy path):
   a. Call `read_comses_files` with `extensions=[".nlogo", ".nlogox"]` to
      get the source content of whichever variant was loaded. Always include
      both extensions — Section 4.4 may have selected an `.nlogox` file.
   b. Scan the source for `to <name>` procedure names and `to-report <name>` reporters (treat the latter as candidates for plausible state metrics; the AI cannot reliably classify utility reporters every time, and that's accepted for v1).
   c. **Fallback if nothing useful is found:** if no procedure with a name resembling `setup` / `initialize` / `start` exists, OR no candidate reporters are found, **stop after loading.** Do not force-run commands the model doesn't define. Report the discovered procedures/reporters (if any) and ask the user which to run.
   d. If a plausible setup + reporter set exists, run them: one `command(<setup>)` call, then a short `run_simulation` with the discovered reporters, then `export_view`.
   e. **Runtime-error stop rule:** if the discovered setup `command(...)` call returns an error (model expected parameters, input files, a different invocation order, etc.), **stop and ask the user.** Do not guess alternate setup names or retry with different arguments. Report the error and the discovered procedure list verbatim.
   f. Summarize results, referencing the ODD doc content obtained via `read_comses_files`.
5. If not NetLogo:
   a. The `open_comses_model` call already downloaded and extracted the archive.
   b. Call `read_comses_files` to get the ODD doc and a summary of what the model does.
   c. State the language clearly, show citation, summarize the ODD findings, and stop.
   d. Do not auto-translate. If the user later explicitly asks to translate, see "On Translation" below.

### On Translation (Optional Follow-up Only)

Not a v1 headline feature. On explicit user request:

- Use `read_comses_files` to get source + ODD.
- Write an equivalent NetLogo model; use `create_model` to load it.
- State what was simplified or skipped (e.g. NumPy vectorized math → plain NetLogo list ops; networkx graph → links, may need `nw` extension).
- Recommend the user verify against the original paper's expected outputs.

Quality depends heavily on source complexity — simple Python Mesa maps cleanly; GIS-heavy or networkx-heavy sources usually don't. Be honest in each case.

### 4.6 Cache semantics (shared by download and open)

#### Resolving `"latest"` to a concrete version (mandatory)

Both `download_comses_model` and `open_comses_model` accept `version="latest"`.
**Cache paths MUST NOT use the literal string `"latest"`.** That would let a
stale 1.0.0 serve forever even after the author publishes 1.1.0.

Algorithm:
1. If the caller passes `version="latest"`, first call `get_codebase` (one
   cheap JSON request) and read `latestVersionNumber` (e.g. `"1.1.0"`).
2. From that point on, treat the version as the concrete string. Use it for
   the cache directory name, the marker check, the download URL, and the
   returned result.
3. Never write a directory named `latest/` under `models/comses/{uuid}/`.

**Snapshot semantics:** the resolution happens once per call. If the author
publishes a newer version mid-download, the in-flight operation stays pinned
to whatever version was resolved at step 1; the next caller asking for
`"latest"` will resolve again and may get the newer version. This is the
intended behavior — `"latest"` means "latest at call time," not "track HEAD."

The JSON returned to the AI includes the resolved `version` so the caller
sees exactly what was used.

#### Cache directory trust rules

A cached `models/comses/{uuid}/{concrete_version}/` directory is trusted
**only** when its `.comses_complete` marker is present.

| Scenario | Behavior |
|----------|----------|
| Directory absent | Download, extract, mark complete. |
| Directory present, marker present | Reuse cache. |
| Directory present, marker absent | Wipe directory, redownload. |
| Download fails mid-stream | Temp files cleaned up; cache dir never created. |
| Extraction fails mid-way | Temp extracted dir cleaned up; cache dir never created. |
| Final dir appeared between our temp-extract and our move (race) | Check for the marker. If another writer finished and marked it, use theirs; discard our temp. If still unmarked, assume orphan — wipe it and retry the move once. |

#### Concurrency assumption (v1)

v1 assumes **single-process access per workspace.** One MCP server process,
serialized tool calls. This matches the common deployment: one user, one
Claude Code / Cursor session, one MCP server. No inter-process locking in v1.

If a second process races on the same `uuid/{version}`, the worst case is a
redundant download and a single orphaned temp directory. The fixed path
validation and marker logic ensure no corruption — only wasted work. A
proper `fcntl`/`portalocker` lock can be added in v2 if multi-process use
becomes a real pattern.

This is explicitly documented here rather than handwaved elsewhere.

---

## 5. File Layout & New Code

```
src/netlogo_mcp/
├── comses.py            # NEW: low-level COMSES API client + safe extract helpers
├── tools.py             # + 5 new tools that delegate to comses.py
├── prompts.py           # + 1 new prompt (explore_comses)
└── config.py            # + COMSES_MAX_DOWNLOAD_MB env var
tests/
├── test_comses.py       # NEW: mocked HTTP + zip safety tests
└── fixtures/comses/     # NEW: captured JSON responses + test zip archives
    ├── search_result.json
    ├── codebase_detail.json
    ├── release_detail.json
    ├── good_archive.zip
    └── malicious_traversal.zip  # for zip-slip test
```

No new resources. Minimal surface area. The `read_comses_files` MCP tool covers what an ODD resource would have.

### `comses.py` module

Thin wrapper over the HTTP API. Pure functions, no MCP coupling. Easy to unit test.

```python
class ComsesClient:
    BASE_URL = "https://www.comses.net"
    def __init__(self, client: httpx.AsyncClient | None = None) -> None: ...
    async def search(self, query: str, page: int = 1) -> dict: ...
    async def get_codebase(self, identifier: str) -> dict: ...
    async def get_release(self, identifier: str, version: str) -> dict: ...
    async def head_download(self, identifier: str, version: str) -> tuple[int, str]: ...
    async def stream_download(self, identifier: str, version: str, dest: Path) -> Path: ...
```

### Dependencies (pyproject.toml)

Add to `[project].dependencies`:
```toml
"httpx>=0.27",
```

Everything else is stdlib (`zipfile`, `pathlib`, `json`).

---

## 6. Tests (Mocked, No Network)

```python
# test_comses.py

# API client
def test_search_builds_correct_url(): ...
def test_search_parses_paginated_response(): ...
def test_get_codebase_returns_title_and_releases(): ...
def test_get_comses_model_includes_citation_text(): ...

# Download path — size enforcement
def test_head_refuses_when_content_length_exceeds_cap(): ...
def test_stream_aborts_mid_download_on_size_overrun(): ...
def test_stream_download_rejects_non_zip_content_type(): ...

# Download path — retry policy
def test_retries_on_502_503_504(): ...
def test_does_not_retry_on_4xx(): ...
def test_gives_up_after_max_retries(): ...

# Extraction — zip safety (critical)
def test_rejects_zip_with_path_traversal(): ...     # ../etc/passwd member
def test_rejects_zip_with_absolute_path_member(): ...
def test_rejects_zip_bomb_by_uncompressed_sum(): ...
def test_atomic_move_on_success(): ...              # temp dir → final dir
def test_cleans_up_temp_on_extract_failure(): ...
def test_completion_marker_written_on_success(): ...

# Cache behavior
def test_reuses_cached_dir_when_marker_present(): ...
def test_redownloads_when_marker_absent(): ...
def test_latest_is_resolved_to_concrete_version_before_caching(): ...
def test_race_orphan_without_marker_is_cleaned_and_retried_once(): ...

# Tool-level integration
def test_extract_finds_nlogo_files(): ...
def test_extract_detects_language_from_codemeta(): ...
def test_open_comses_model_loads_netlogo(): ...
def test_open_comses_model_returns_fallback_for_non_netlogo(): ...
def test_read_comses_files_respects_byte_cap(): ...
def test_read_comses_files_truncates_and_sets_flag(): ...
def test_read_comses_files_omits_files_with_reasons(): ...
def test_read_comses_files_priority_odd_first_then_nlogo(): ...
def test_read_comses_files_errors_when_cache_missing(): ...
```

Use `httpx.MockTransport` to fake the COMSES API in tests. Fixtures: real captured JSON responses + two test zip archives (one good, one crafted with a traversal path) saved under `tests/fixtures/comses/`.

Target: ~20 new tests. Zip-safety tests are non-optional. Overall suite still under 10 seconds.

---

## 7. Documentation Updates

- `README.md`: add a "COMSES Integration" section with a demo prompt.
- `docs/DEVELOPMENT.md`: update project structure to list `comses.py`.
- `docs/CLIENTS.md`: no changes (all clients work).
- `CHANGELOG.md`: new entry under "Unreleased / COMSES support".
- Obsidian `Implementation Status.md` + `Working Notes.md`: record the feature landing.

---

## 8. User Flow (End-to-End Demo)

User (in Claude Code):
> "Find me an agent-based model for rumor spreading on COMSES and run a short baseline."

Server (happy path, NetLogo model):
1. `search_comses("rumor spreading")` → N matches.
2. AI picks a top peer-reviewed NetLogo match.
3. `get_comses_model(uuid)` → AI presents title, authors, **citation text**, license.
4. `open_comses_model(uuid)` → resolves `"latest"` to concrete version, downloads safely (or uses cache), extracts, picks the right `.nlogo` file per Section 4.4 rules, loads it into NetLogo.
5. `read_comses_files(uuid, extensions=[".nlogo", ".nlogox"])` → AI reads the actual source (whichever variant was loaded per Section 4.4) to **discover** real procedure names and reporters. **The AI does not fabricate commands.**
6. **Branch based on discovery:**
   - **Plausible setup + useful reporters found:** `command("<discovered setup>")`. If that call returns an error, **stop and ask the user** — do not guess alternates. Otherwise → `run_simulation(<N ticks>, [<discovered reporters>])` → `export_view()`.
   - **No plausible setup OR no useful reporters found:** stop after loading. Report to the user what was found (maybe just `setup` with no reporters, or an unusual procedure name). Ask which procedure to run or whether they want to inspect the source first.
7. `read_comses_files(uuid, extensions=[".md", ".txt"], max_total_bytes=50000)` → AI reads the ODD doc and summarizes what the model demonstrates.

Non-NetLogo model flow:
1. `search_comses("rumor spreading")` → top match is Python.
2. `get_comses_model(uuid)` → citation text + metadata.
3. `open_comses_model(uuid)` → downloads + extracts (but does NOT load NetLogo). Returns the non-NetLogo JSON with language, code paths, ODD doc path.
4. `read_comses_files(uuid, extensions=[".md", ".txt"])` → AI reads the ODD doc.
5. AI reports: "This model is in Python (Mesa). It was downloaded to models/comses/... and I read the ODD documentation — here is a summary: [...]. I can explain the source code, or, if you explicitly ask, translate it to NetLogo (approximately). Otherwise we stop here."
6. Flow stops unless user asks to translate.

Total time in warm session for happy path: realistically **30–60 seconds**, dominated by the download and the HTTP round-trips to COMSES.

---

## 9. Implementation Order (4 Chunks, v1)

Estimates are for focused work, assuming no surprise blockers.

1. **Chunk 1 (~1.5 hours):** `comses.py` with `search`, `get_codebase`, `get_release` methods and the **retry policy** (specific codes + backoff). Mocked unit tests for API client + retry. `search_comses` + `get_comses_model` MCP tools.

2. **Chunk 2 (~2 hours):** Safe download + extract pipeline. `stream_download` with mid-stream byte enforcement + non-zip content-type rejection. Safe zip extraction with path validation and zip-bomb guard. Atomic temp→final rename. `.comses_complete` marker. `download_comses_model` tool. ~6 tests covering these paths including the malicious-zip fixture.

3. **Chunk 3 (~1.5 hours):** `open_comses_model` cache-aware tool with language-detection fallback. `read_comses_files` tool with byte cap + truncation flag. Tests for both.

4. **Chunk 4 (~1 hour):** `explore_comses` prompt (NetLogo-first, source-introspection, no fabricated commands). README + CHANGELOG + Obsidian updates. Live manual test against real COMSES with one NetLogo model and one non-NetLogo model.

Total focused time: **~6 hours**. Realistic spread: 1–2 evenings. This is an **honest estimate** — the earlier "4 hours" underestimated zip safety, retry logic, and cross-client file access, all of which are now first-class work.

---

## 9.5. What's Explicitly NOT in v1 (Deferred)

These items were considered and intentionally skipped. Each has a reason.

| Deferred item | Why not now |
|---------------|-------------|
| `netlogo://comses/{uuid}/odd` resource | `read_comses_files` covers the same need without URI-scheme ceremony. If we later want fine-grained per-doc URIs, we can add them. |
| Separate `convert_comses_to_netlogo` prompt | Translation is a *possible* user request, not a v1 promise. A dedicated prompt would over-market it. |
| GitHub model fetching | Serge mentioned it, but COMSES alone gives him 90% of what he asked for. Different API, different archive format, different auth for rate limits. Scope for v2 if asked. |
| Automatic cleanup of old downloads | Manual cleanup is fine for early users. A `cleanup_comses_downloads` tool can be added if `models/comses/` disk usage becomes a complaint. |
| Parsing `codemeta.json` into a structured MCP object | We *read* it at download-time for language detection, but don't expose it as its own resource. Pure nice-to-have. |
| `netlogo_only` search filter | Explicitly removed — we trust AI and user to interpret language info per result. Hiding non-NetLogo would hide ~80% of the library. |
| Uploading / publishing models back to COMSES | Write API requires auth and is out of scope. Read-only forever. |
| Parallel downloads | One at a time is fine for interactive use. Complicates retry and rate-limit story for no real win. |

This is a deliberate design choice: **correct and narrow > broad and shaky.**

---

## 10. After Shipping

Once v1 lands, the natural next ask is a **"research workflow" tool** — log
parameters, save batches, export reproducible experiment bundles — which maps
directly to the "automating policy workflows" section of the COMSES team's
own paper. That work is out of scope for v1 but listed here as the obvious
follow-up direction.

---

## 11. Open Questions (For Self or Future)

- Should we cache COMSES search results on disk between sessions? (Probably no — library updates frequently, and re-fetching 10KB of JSON is cheap.)
- Should we fetch from GitHub too, as Serge mentioned? (Phase 2 — different API, different auth for rate limits, different archive format. Ship COMSES first.)
- Should we parse `codemeta.json` into a structured resource? (Nice-to-have for v2. We already read it at download-time for language detection.)
- Multi-process cache access: handled in v1 by the "single-process per workspace" assumption documented in Section 4.6. If real multi-process usage emerges, add a `portalocker` or `fcntl` file lock on the cache dir.
- Handling `.nlogox` vs `.nlogo` format differences in COMSES models that pre-date NetLogo 7: unclear if older NetLogo 6 `.nlogo` files always load cleanly in NetLogo 7. Not a v1 blocker — `open_model` already exists and we use it — but worth watching.
