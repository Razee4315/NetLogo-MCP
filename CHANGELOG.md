# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.1] - 2026-06-06

### Added — official MCP Registry listing

- Published to the [official MCP Registry](https://registry.modelcontextprotocol.io)
  as `io.github.razee4315/netlogo-mcp` — MCP clients that browse the registry
  can now discover and install the server directly.
- `server.json` registry manifest with PyPI package reference and
  documented `NETLOGO_HOME` / `JAVA_HOME` / `NETLOGO_GUI` environment
  variables.
- Release workflow now publishes to the MCP Registry (GitHub OIDC, no
  tokens) after the PyPI publish succeeds.
- README carries the registry ownership marker (`mcp-name`, hidden
  comment) required for PyPI package validation.

## [1.0.0] - 2026-06-06

First stable release. The server is feature-complete for conversational
agent-based modeling: 25 tools covering model creation with declarative
widgets, simulation and data collection, BehaviorSpace parameter sweeps,
CoMSES Net library access, and view/world export — now published on PyPI
as [`netlogo-mcp`](https://pypi.org/project/netlogo-mcp/).

### Packaging

- Published to PyPI: `pip install netlogo-mcp`.
- Package renamed `NetLogo_MCP` → `netlogo-mcp` (PyPI-normalized name);
  version is now single-sourced from `netlogo_mcp.__version__`.
- Added release automation: pushing a `v*` tag builds, publishes to PyPI
  via trusted publishing, and creates a GitHub Release with these notes.
- Added `CITATION.cff`, issue/PR templates, and Dependabot config.

### Changed — lazy JVM startup

- The JVM (and the NetLogo GUI window) now starts **lazily** on the first
  tool call that needs the workspace, instead of the moment an MCP client
  connects. Connecting Claude/Cursor/etc. no longer pops a NetLogo window
  you didn't ask for. Startup runs on a worker thread under the workspace
  lock, so the event loop and MCP heartbeats stay responsive during the
  30-60s boot. Set `NETLOGO_EAGER_START=true` to restore the old
  boot-at-launch behavior.
- `server_info` now reports `jvm_started` so clients can check workspace
  state without triggering a boot.

### Fixed — JVM startup deadlock on Windows

- The stdio transport keeps a pending blocking read on the stdin pipe from
  a worker thread; Windows serializes operations on a synchronous pipe's
  file object, so the JVM's std-handle probes during `CreateJavaVM` blocked
  behind that read — JVM startup hung until the client happened to send
  another byte. The server now hands the transport a private duplicate of
  stdin and points fd 0 (and the Win32 `STD_INPUT_HANDLE`) at devnull, so
  the JVM never touches the protocol pipe. This was the real reason an
  earlier lazy-startup attempt was abandoned for eager startup.

### Fixed — protocol corruption on NetLogo errors

- pynetlogo `print()`s Java stack traces to stdout whenever a NetLogo
  command/reporter/load fails — and stdout is the MCP JSON-RPC channel.
  One compile error in generated model code could corrupt the protocol
  stream and leave the session flaky. The server now duplicates fd 1 for
  the transport's private use, points fd 1 at stderr (covering the JVM's
  direct `System.out` writes, which bypass Python entirely), and parks
  Python's `sys.stdout` on stderr for the whole serving phase.

### Fixed — widget generation

- `create_model` / `save_model` no longer emit Setup/Go buttons for
  procedures that don't exist in the code — a button pointing at a missing
  procedure made the whole model fail to load.
- `to setup-patches` no longer falsely counts as defining `setup`.

### Changed — multi-column widget layout

- Declarative widgets now wrap into additional columns when they'd
  overflow the column height, and the world view shifts right to sit
  beside the last column — widget-heavy models no longer pile into one
  endless strip that runs off the bottom of the window.

### Added — GUI polish

- The NetLogo window is retitled to the model name and brought to the
  front whenever a model is loaded (`create_model` / `open_model` /
  `update_model` / `open_comses_model`). Best-effort via the Swing event
  thread; silent no-op in headless mode.
- New `watch_simulation(ticks, delay_ms)` tool — runs `go` step-by-step
  with a pause between steps so a human can actually watch the dynamics
  unfold in the GUI. Capped at 120s per call; `run_simulation` remains the
  full-speed data-collection path.

### Added — plot widgets

- The `widgets` schema now supports `{"type": "plot", "pens": [...]}` —
  live population-dynamics plots in the NetLogo window, the main reason to
  watch a GUI run. Pens take NetLogo plot code, palette color names (or raw
  AWT ints), line/bar/point modes, and intervals; axes auto-scale.
  Verified live: NetLogo 7.0.3 loads the generated XML and pens plot every
  tick.

### Added — update_model

- New `update_model(code, widgets?)` tool: rewrites the currently loaded
  `.nlogox` in place and reloads it. Existing widgets are preserved when
  `widgets` is omitted, so iterating on procedures keeps the interface the
  user already has. Ends the one-`_created_*.nlogox`-file-per-iteration
  clutter in the models directory.

### Added — declarative interface widgets

- `create_model` and `save_model` accept an optional `widgets` list:
  sliders, switches, buttons, and monitors with validated names, escaped
  code, and automatic column layout (NetLogo 7 `.nlogox` widget schema).
  Slider/switch widgets define their variable, so generated models can use
  interface globals exactly like hand-built ones — and `set_parameter`
  works against them out of the box.

### Docs

- README slimmed to the essentials; full tool reference moved to
  `docs/TOOLS.md`, environment variables and GUI/headless guidance to
  `docs/CONFIGURATION.md`, and the security model to `docs/SECURITY.md`.
- `docs/DEVELOPMENT.md` architecture notes rewritten to match the lazy
  startup and fd-level stdout discipline (the old notes contradicted the
  code on threading).

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
