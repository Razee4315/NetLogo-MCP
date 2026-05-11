# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security & validation

- `set_parameter` now validates the `name` argument against a NetLogo
  identifier regex before interpolating it into a `set <name> <value>`
  command. Closes a command-injection vector where a name like
  `"x setup -- "` would have appended an arbitrary NetLogo command past
  the `set`. Legitimate kebab-case + predicate names (`show-energy?`,
  `initial-number-sheep`) are unaffected.
- `run_simulation` rejects empty / non-string entries in `reporters`,
  and `get_patch_data` rejects blank `attribute`s — these formerly
  produced confusing NetLogo compile errors deep in the call.
- 25 new tests cover the validation surface (injection-shape names,
  blank reporters, blank attributes).

### Added — workspace control & introspection

- New `close_model` tool — issues `clear-all` and forgets the current
  model path so AI clients can drop pending state without bouncing the
  JVM (which costs 30-60s on the next startup).
- New `server_info` tool — pure config / filesystem inspection that
  returns server version, GUI mode, configured paths, and whether the
  BehaviorSpace headless launcher is reachable. Useful as a pre-flight
  check before launching long sweeps; does not require the JVM to be
  warm.

### Removed

- Dead `get_or_create_netlogo` lazy-init helper in `server.py` — the
  eager `lifespan()` startup is the only path now, and the duplicated
  init was an attractive nuisance for future contributors.

### Added — BehaviorSpace integration & NetLogo 7 transition guide

- 3 new tools for running NetLogo BehaviorSpace experiments:
  `list_experiments` (read saved experiments from `.nlogox`),
  `preview_experiment` (show run plan without executing),
  `run_experiment` (drive the headless launcher in a separate JVM and
  return parsed table-CSV results).
- Drives BehaviorSpace via the canonical `NetLogo_Console` /
  `netlogo-headless` launcher — no dependency on the unbundled `bspace`
  extension, works with NetLogo 6.x and 7.x.
- Hard run cap (`max_total_runs`, default 200) and wall-clock timeout
  (`timeout_seconds`, default 600). Partial table CSV is preserved on
  timeout; the runner reports `timed_out` separately from `failed`.
- New prompt: `behaviorspace_experiment` — enforces preview-before-run.
- New resource: `netlogo://docs/transition` — focused 6→7 porting guide
  for AI clients hitting old CoMSES models. Covers `.nlogo` →
  `.nlogox` auto-conversion, `ifelse-value` precedence shift, `task` →
  anonymous procedures, movie-prim → `vid` extension, bundled vs
  non-bundled extensions in 7.0.3.
- Tracks `current_model_path` in the lifespan context so BehaviorSpace
  can target the model the AI most recently loaded without an extra arg.

### Changed — token efficiency

- `run_simulation` accepts `summary_only=True` (returns
  min/mean/max/std/final per reporter as one row each) and `max_rows=N`
  (evenly-spaced decimation that always keeps the final tick).
- `get_patch_data` accepts `summary_only=True` (returns shape + numeric
  stats + unique-count instead of the full 2D grid).
- Defaults are unchanged; existing prompts keep working.

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
