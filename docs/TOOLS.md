# Tool Reference

Every tool exposed by NetLogo MCP, plus the widget schema, BehaviorSpace
workflow, and CoMSES Net integration details.

## Core tools

| Tool | Description |
|------|-------------|
| `create_model(code, widgets?)` | Create a new model from NetLogo code (envelope + widgets added automatically) |
| `update_model(code, widgets?)` | Rewrite the loaded model's code **in place** and reload — existing widgets are preserved unless new ones are given. Prefer this over `create_model` when iterating. |
| `open_model(path)` | Load an existing .nlogo/.nlogox model |
| `command(netlogo_command)` | Execute a NetLogo command (setup, go, etc.) |
| `report(reporter)` | Evaluate a reporter expression |
| `run_simulation(ticks, reporters)` | Run N ticks, collect data as a table |
| `set_parameter(name, value)` | Set a global variable / slider / switch |
| `get_world_state()` | Get tick count, agent counts, world dimensions |
| `get_agent_sample(breed, n, attributes)` | Sample N agents as a markdown table — fills the gap between counts and hand-crafted reporters |
| `get_patch_data(attribute, max_cells)` | Get patch data as a 2D grid (for heatmaps); auto-downsamples above `max_cells` (default 10000) |
| `export_view()` | Export current view as PNG image |
| `save_model(name, code, widgets?)` | Save model to file |
| `export_world()` | Export full world state to CSV |
| `close_model()` | Unload the current model and `clear-all` the workspace |
| `server_info()` | Inspect server config (paths, GUI mode, JVM state, headless launcher) |
| `list_models()` | List model files in models directory |

> **First JVM-touching call takes 30-60 seconds** — the JVM starts lazily on
> the first `open_model` / `create_model` / `open_comses_model` call. Every
> call after that is instant. `server_info` reports `jvm_started` so you can
> check the state without triggering a boot.

## Interface widgets

`create_model` and `save_model` accept an optional `widgets` list so models
get a real, usable interface (sliders, switches, buttons, monitors) instead
of just code:

```json
[
  {"type": "slider",  "variable": "num-sheep", "min": 0, "max": 250,
   "default": 100, "step": 1, "label": "Sheep", "units": "animals"},
  {"type": "switch",  "variable": "show-trails?", "default": false},
  {"type": "button",  "code": "setup", "label": "Setup"},
  {"type": "button",  "code": "go", "label": "Go", "forever": true},
  {"type": "monitor", "code": "count sheep", "label": "Sheep", "precision": 0},
  {"type": "plot", "label": "Populations", "x_axis": "time", "y_axis": "count",
   "pens": [
     {"code": "plot count sheep",  "label": "sheep",  "color": "green"},
     {"code": "plot count wolves", "label": "wolves", "color": "red"}
   ]}
]
```

Plot pens redraw every tick (and on `update-plots`). Pen `color` accepts a
palette name (`black`, `gray`, `white`, `red`, `orange`, `brown`, `yellow`,
`green`, `lime`, `turquoise`, `cyan`, `sky`, `blue`, `violet`, `magenta`,
`pink`) or a raw AWT integer; unspecified pens cycle through distinct
colors. Pen `mode`: 0 = line (default), 1 = bar, 2 = point.

Rules:

- **Slider/switch widgets DEFINE their variable.** Do not also declare it in
  `globals [...]` — NetLogo treats that as a duplicate definition and the
  model won't compile.
- When `widgets` is omitted, Setup/Go buttons are auto-added — but only for
  procedures that actually exist in the code (a button pointing at a missing
  procedure makes the whole model fail to load). A ticks monitor is always
  included.
- When `widgets` is provided, it fully replaces the default button column —
  include your own setup/go buttons.
- Widgets stack in a left-hand column; the world view sits to their right.

## Resources & prompts

4 resources: primitives reference, programming guide, model source,
NetLogo 6→7 transition guide.

5 prompts: `analyze_model`, `create_abm`, `parameter_sweep`,
`explore_comses`, `behaviorspace_experiment`.

## BehaviorSpace integration

Run NetLogo's BehaviorSpace experiments from any MCP client. Three tools
cover the workflow:

1. **`list_experiments()`** — read the `<experiments>` section of the loaded
   `.nlogox` to inventory saved experiments. No JVM round-trip; instant.
2. **`preview_experiment(...)`** — show the run plan (total runs, parameter
   combos, time estimate) without executing. Always run this before a long
   sweep.
3. **`run_experiment(...)`** — drive `NetLogo_Console --headless` (or
   `netlogo-headless.bat`) in a separate JVM. Returns parsed results plus
   the path to the full table CSV.

Long runs are bounded by `max_total_runs` (default 200) and
`timeout_seconds` (default 600); partial table CSV is preserved on timeout.

Try it with the `behaviorspace_experiment` prompt or just ask: *"Run a
BehaviorSpace experiment varying initial-density from 50 to 90 in steps of
10, three reps each, measuring count turtles."*

## CoMSES Net integration

NetLogo MCP can search and safely fetch any model from the
[CoMSES Net computational model library](https://www.comses.net/) — the
largest peer-reviewed ABM repository. NetLogo models load automatically;
Python / R / Julia models are identified and cached locally so you can
inspect their source and ODD documentation from any MCP client, including
clients with no filesystem tools.

| Tool | Description |
|------|-------------|
| `search_comses(query)` | Search the CoMSES Net model library |
| `get_comses_model(uuid)` | Fetch metadata + citation text for one model |
| `download_comses_model(uuid)` | Safely download + extract an archive |
| `open_comses_model(uuid)` | Download (or reuse cache) and load NetLogo models |
| `read_comses_files(uuid)` | Read ODD / source contents from a downloaded model |

Try it with the `explore_comses` prompt or just ask: *"Find me a
predator-prey ABM on COMSES and run a short baseline."*

Download safety properties are documented in [SECURITY.md](SECURITY.md).

## Token-efficient output

For long runs, `run_simulation` supports:

- `summary_only=True` — return only min/mean/max/std/final per reporter
  instead of the full per-tick table.
- `max_rows=N` — decimate by evenly-spaced sampling (always keeps the
  final tick).

`get_patch_data` auto-downsamples grids above `max_cells` (default 10000).
