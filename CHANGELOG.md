# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — CoMSES Net integration

- 5 new tools for exploring the CoMSES Net computational model library:
  `search_comses`, `get_comses_model`, `download_comses_model`,
  `open_comses_model`, `read_comses_files`.
- 1 new prompt: `explore_comses` — NetLogo-first, source-introspection,
  never fabricates commands, stops-and-asks on runtime errors.
- Safe download pipeline: HEAD screen + mid-stream byte cap
  (`COMSES_MAX_DOWNLOAD_MB`, default 50), zip-member path-traversal
  validation, zip-bomb guard, atomic temp-to-final extract with
  `.comses_complete` marker, race reconciliation.
- `"latest"` version resolution with snapshot semantics — resolved to
  a concrete version before any cache path is computed; the resolved
  version is returned so follow-up reads stay pinned.
- `read_comses_files` returns a precise contract with per-file
  `{content, full_size, returned_size, truncated}`, priority ordering
  (ODD → NetLogo → other code → md/txt), byte cap with line-boundary
  truncation, UTF-8 decoding with `errors="replace"`, zero-match case
  handled explicitly.
- `httpx>=0.27` dependency.
- 44 new tests covering retry matrix, zip-slip, zip-bomb, marker,
  race-orphan, NetLogo-file selection rule, ODD discovery, cache
  reuse, latest resolution, truncation, extension filters, prompt rules.

## [0.1.0] - 2025-02-23

### Added

- Initial release of NetLogo MCP Server
- 12 tools: `open_model`, `command`, `report`, `run_simulation`, `set_parameter`, `get_world_state`, `get_patch_data`, `export_view`, `create_model`, `list_models`, `save_model`, `export_world`
- 3 resources: `netlogo://docs/primitives`, `netlogo://docs/programming`, `netlogo://models/{name}`
- 3 prompts: `analyze_model`, `create_abm`, `parameter_sweep`
- Headless and GUI mode support
- Built-in NetLogo primitives reference and programming guide
- Path traversal protection on all file operations
- XML escaping for `.nlogox` model creation
- Stdout protection to prevent JVM corruption of MCP stdio transport
- Mock-based test suite (no Java/NetLogo needed to run tests)
- Cross-platform JVM detection (Windows, Linux, macOS)
