# COMSES Integration Plan

Research + design doc for extending NetLogo MCP with COMSES model library access.

Audience: future contributors, Serge/Jiaan (as demo material), my own implementation reference.

---

## Ship Philosophy

**Ship v1 in ~4 hours. Expand only when asked.**

Serge said trust is earned through delivery. A working v1 in his hands in 5 days > a complete v2 in 2 weeks. This plan is intentionally minimal — the fewer tools, the faster we ship, the sooner we learn from real use.

---

## 1. Goal

Enable NetLogo MCP to:
1. Search the CoMSES Net Computational Model Library
2. View model metadata (authors, license, releases, citations)
3. Download any model from COMSES to the local `models/` folder
4. Load NetLogo models directly; return structured info for non-NetLogo models so the AI can offer to translate

This fulfills Serge Stinckwich's direct request on 2026-04-17:
> "Would be nice if there an agent skills to explore existing ABM on COMSES or github"

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

Mitigation:
- Default download cap: **50MB** (configurable via env var `COMSES_MAX_DOWNLOAD_MB`).
- Before downloading, send a `HEAD` request, read `Content-Length`, warn or refuse if above cap.
- Stream the download to disk (don't buffer in memory).

### Medium: Language tag filter (`programming_languages=19`) returns 0 results

The tag filter does not map to internal language IDs. Must either:
- Use text query `query=NetLogo` (returns 235 — matches models with "NetLogo" in text)
- Filter client-side after fetch by inspecting `release.releaseLanguages`

Mitigation:
- In `search_comses`, accept a `language` param that we use via `query=` when it's "NetLogo".
- After fetching a candidate, re-verify with the release's `releaseLanguages` field before recommending.

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

### Low: Cloudflare occasional hiccups

One of three consecutive rapid downloads returned an HTML error page once, then succeeded on retry.

Mitigation:
- Retry once on non-2xx with a 2s back-off.
- `httpx` has `AsyncClient` with retries configurable.

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
- Expose the raw file to Claude as a resource if it's a text format. PDFs skip for now.

### Low: Models may not be loadable by NetLogo MCP

If the model is Python (Mesa), R, Julia, or Java, it's not runnable through our NetLogo bridge.

Mitigation:
- Before attempting `open_model`, inspect `releaseLanguages` field.
- If not NetLogo, return the download path and tell the user the language and that they'll need a different tool to run it.

---

## 4. Tool Design (v1)

**Four MCP tools.** All async, use `httpx.AsyncClient`. No filtering that hides results from the user — language info is surfaced per result so AI/user can decide.

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

```python
@mcp.tool()
async def download_comses_model(
    ctx: Context,
    identifier: str,
    version: str = "latest",
    max_mb: float = 50.0,
) -> str:
    """Download a COMSES model archive to the local models directory.

    Args:
        identifier: Full model UUID.
        version: Version string (e.g. '1.0.0') or 'latest'.
        max_mb: Max download size in MB. Fails with clear error if exceeded.

    Returns: summary JSON with
    {saved_path, extracted_files, netlogo_files, odd_doc_path, license, summary}
    """
```

Implementation details:
- HEAD request first to check size.
- Stream download to `models/comses/{uuid}/{version}/` to keep per-model isolation.
- Extract zip into same directory.
- Scan for `.nlogo` / `.nlogox` files, list them in response.
- Scan for ODD docs, include path in response.

### 4.4 `open_comses_model` (with graceful fallback for non-NetLogo models)

```python
@mcp.tool()
async def open_comses_model(
    ctx: Context,
    identifier: str,
    version: str = "latest",
) -> str:
    """Download a COMSES model. If it's NetLogo, load it. Otherwise report
    back so the AI can offer to convert it.

    Happy path: returns 'Loaded NetLogo model: <filename>'
    Fallback: returns structured JSON with language info, code file paths,
    and a `suggestion` field telling the AI to ask the user whether to
    convert the source to NetLogo.
    """
```

The fallback response shape:

```json
{
  "status": "not_runnable_in_netlogo",
  "language": "Python (Mesa)",
  "title": "SIR Epidemic Model",
  "extracted_path": "models/comses/{uuid}/{version}/",
  "code_files": ["code/model.py", "code/agents.py"],
  "odd_doc": "docs/ODD.md",
  "suggestion": "This is a Python model, not NetLogo. Ask the user if they want me to convert it to NetLogo. If yes, read the files from extracted_path (using your filesystem tools) and use create_model to load the NetLogo translation. Be honest about which parts can and cannot be faithfully translated."
}
```

The `suggestion` field is LLM-readable guidance — it tells Claude / Cursor / etc. what to do next in plain English. Most MCP clients (Claude Code, Cursor, Windsurf, VS Code) have filesystem access, so they can read the code files directly.

### Single Prompt

```python
@mcp.prompt()
def explore_comses(topic: str) -> list[Message]:
    """Full COMSES workflow: search → pick the best model → if NetLogo, load
    and run; if not, offer to translate to NetLogo. Covers the whole flow
    in one prompt template.
    """
```

The prompt instructs the AI to:
1. Search COMSES for models matching the topic
2. Pick the best match (by peer review status, downloads, recency)
3. Show the user the model details + citation
4. If NetLogo: download, load, run a baseline simulation, show results
5. If not NetLogo: tell the user the language, show the ODD doc summary, ask if they want a translation
6. On translation: read the source code, write NetLogo equivalent, call `create_model`, verify with a few ticks
7. Be honest about translation fidelity — name libraries that couldn't be faithfully reproduced

### Honesty Guardrails for Conversion

When translation happens, the AI is prompted to state:

- Which parts of the original it simplified or skipped
- Any domain libraries (NumPy, networkx, geopandas, ggplot) it couldn't faithfully reproduce
- Whether outputs should match the original exactly or are approximations
- That the user should verify against the original paper's expected results

Realistic quality matrix:

| Source | Conversion Quality |
|--------|-------------------|
| Simple Python Mesa (basic agents, no external libs) | Good |
| Python with heavy NumPy math | Mediocre |
| R with ggplot / data.table | Mediocre |
| Java / C++ ABM | Hard (paradigm mismatch) |
| Complex networks (networkx) | Possible with NetLogo `nw` extension |
| GIS-heavy (geopandas, rasters) | Hard (needs NetLogo GIS extension) |

---

## 5. File Layout & New Code

```
src/netlogo_mcp/
├── comses.py            # NEW: low-level COMSES API client (httpx-based)
├── tools.py             # + 4 new tools that delegate to comses.py
├── prompts.py           # + 1 new prompt (explore_comses)
└── config.py            # + COMSES_MAX_DOWNLOAD_MB env var
tests/
├── test_comses.py       # NEW: mocked HTTP tests
└── conftest.py          # + fixtures for mocked COMSES responses
```

No new resources or extra files. Minimal surface area.

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
def test_search_builds_correct_url(): ...
def test_search_parses_paginated_response(): ...
def test_get_codebase_returns_title_and_releases(): ...
def test_get_comses_model_includes_citation_text(): ...
def test_head_download_returns_size_and_content_type(): ...
def test_stream_download_rejects_non_zip(): ...
def test_stream_download_rejects_oversize(): ...
def test_extract_finds_nlogo_files(): ...
def test_extract_detects_language_from_codemeta(): ...
def test_open_comses_model_returns_fallback_for_non_netlogo(): ...
```

Use `httpx.MockTransport` to fake the COMSES API in tests. Fixture: real captured JSON responses saved to `tests/fixtures/comses/`.

Target: ~10 new tests, keep overall suite under 10 seconds.

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
> "Find me an agent-based model for rumor spreading on COMSES and run it for 200 ticks."

Server:
1. `search_comses("rumor spreading")` → 12 matches
2. AI picks top by `downloadCount + peerReviewed`
3. `get_comses_model(uuid)` → shows authors, ODD summary, license
4. `download_comses_model(uuid)` → 180KB zip, extracted to `models/comses/.../1.0.0/`
5. `open_comses_model(uuid)` → NetLogo loads `code/RumorSpread.nlogo`
6. `command("setup")` → model initialized
7. `run_simulation(200, ["count spreaders", "count informed"])` → markdown table
8. `export_view()` → final PNG
9. AI explains results referencing the model's ODD doc

Total time in warm session: **~15–25 seconds**.

---

## 9. Implementation Order (3 Chunks, v1)

1. **Chunk 1 (~1.5 hours):** `comses.py` with `search`, `get_codebase`, `get_release` methods. Mocked unit tests. `search_comses` + `get_comses_model` MCP tools.
2. **Chunk 2 (~1.5 hours):** `stream_download` helper with size guard + non-zip rejection. `download_comses_model` tool. Zip extraction, language detection from `codemeta.json`, NetLogo file scan. Tests.
3. **Chunk 3 (~1 hour):** `open_comses_model` tool with graceful fallback. `explore_comses` prompt. README + CHANGELOG + Obsidian updates.

Total focused time: **~4 hours**. One focused evening.

---

## 9.5. What's Explicitly NOT in v1 (Deferred to v2)

These are documented here to show they were considered but intentionally skipped:

| Deferred item | Why not now |
|---------------|-------------|
| `read_comses_files` tool | Most MCP clients (Claude Code, Cursor, Windsurf, VS Code, Codex) have their own filesystem read tools. Only needed for Claude Desktop if a user there wants translation. Add if requested. |
| `netlogo://comses/{uuid}/odd` resource | After extraction, ODD docs are just files on disk. AI can read them directly. URI resource adds ceremony without meaningful benefit. |
| Separate `convert_comses_to_netlogo` prompt | Covered by the broader `explore_comses` prompt. One prompt is simpler than two overlapping ones. |
| GitHub model fetching | Serge mentioned it, but COMSES first gives him 90% of what he asked for. Different API, different archive format, different auth for rate limits. Scope for v2. |
| Cleanup of old downloads | Not urgent. If `models/comses/` gets large, users can delete it manually or we add a tool later. |
| Download caching / dedup across sessions | Reruns of `download_comses_model` check if target dir already exists, skip re-download. Simple early optimization, not worth more. |
| Parsing `codemeta.json` into a structured resource | Nice-to-have. Current approach: we read it at download-time to detect language, but don't expose it as its own MCP object. |
| `netlogo_only` search filter | Explicitly removed — we trust AI and user to interpret language info per result. Hiding non-NetLogo would hide ~80% of the library. |

This is a deliberate design choice: **ship something Serge can use in a week, not something "complete" in a month.**

---

## 10. After Shipping

1. Push to main; notify Serge on WhatsApp with:
   - Link to the commit / release.
   - A 30-second screen capture showing the full flow.
2. Ask Jiaan separately if he wants to try it first-hand.
3. Update Obsidian `External Validation and Collaboration.md` with the delivery timeline.
4. Plan next ask: **add a "research workflow" tool** — log parameters, save batches, export reproducible experiment bundles — which directly maps to their paper's "automating policy workflows" section.

---

## 11. Open Questions (For Self or Future)

- Should we cache COMSES results on disk between sessions? (Probably no — library updates frequently, and re-fetching 10KB of JSON is cheap.)
- Should we fetch from GitHub too, as Serge mentioned? (Phase 2 — different API, different auth for rate limits, different archive format. Ship COMSES first.)
- Should we parse codemeta.json into a structured resource? (Yes, eventually — would let an AI read authorship, license, versioning without re-hitting the network.)
- Multi-user safety: if two Claude sessions run `download_comses_model` for the same UUID concurrently, do we race? (Use a lockfile in the model directory, or just don't worry — MCP tools are typically serialized already per session.)
