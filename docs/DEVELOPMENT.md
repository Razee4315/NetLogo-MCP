# Development Guide

## Project Structure

```
NetLogo_MCP/
├── pyproject.toml              # Package config, linting & type check settings
├── smithery.yaml               # Smithery registry configuration
├── .mcp.json                   # MCP client configuration (works with any client)
├── .pre-commit-config.yaml     # Pre-commit hooks (ruff, mypy)
├── .github/workflows/ci.yml    # CI pipeline (lint, type check, test)
├── CHANGELOG.md                # Version history
├── docs/
│   ├── TOOLS.md                # Full tool reference, widget schema, BehaviorSpace & CoMSES
│   ├── CONFIGURATION.md        # Environment variables, GUI/headless, startup timing
│   ├── SECURITY.md             # Security model and trust boundary
│   ├── CLIENTS.md              # Setup instructions for all 11 MCP clients
│   └── DEVELOPMENT.md          # This file
├── src/
│   └── netlogo_mcp/
│       ├── server.py           # FastMCP app, stdout protection, lifespan
│       ├── tools.py            # All 20 tools (12 NetLogo + 5 CoMSES + 3 BehaviorSpace)
│       ├── comses.py           # CoMSES Net API client + safe zip extract
│       ├── bspace.py           # BehaviorSpace XML build/parse + headless launcher driver
│       ├── resources.py        # 4 resources (primitives, programming, model source, transition)
│       ├── prompts.py          # 5 prompts (analyze, create, sweep, explore_comses, behaviorspace)
│       ├── config.py           # Environment variable loading
│       ├── py.typed            # PEP 561 type marker
│       └── data/
│           ├── primitives.md   # NetLogo primitives reference
│           ├── programming_guide.md
│           └── netlogo7_transition.md  # NetLogo 6→7 porting checklist
├── models/                     # Drop your .nlogo/.nlogox files here (empty by default)
├── exports/                    # PNG views, world CSVs, and BehaviorSpace results
│   └── experiments/            # BehaviorSpace setup XMLs + table CSVs
└── tests/
    ├── conftest.py             # Mock fixtures (no JVM needed)
    ├── manual_smoke.py         # Live end-to-end check (real NetLogo, run by hand)
    ├── test_server.py
    ├── test_tools.py
    ├── test_bspace.py          # BehaviorSpace XML/parse/CSV unit tests (no JVM)
    ├── test_bspace_tools.py    # MCP tool wrappers with subprocess mocked out
    ├── test_comses.py          # CoMSES integration: API, zip safety, tools, prompt
    ├── test_resources.py
    └── fixtures/comses/        # Captured JSON fixtures for CoMSES tests
```

## Tech Stack

- **Server:** [FastMCP](https://gofastmcp.com/) (Python)
- **NetLogo Bridge:** [pynetlogo](https://github.com/quaquel/pynetlogo) + [JPype](https://github.com/jpype-project/jpype)
- **Runtime:** NetLogo JVM (GUI or headless)
- **Transport:** MCP stdio protocol
- **Linting:** Ruff
- **Type checking:** mypy
- **Tests:** pytest, pytest-asyncio, pytest-cov
- **Build:** Hatchling

## Running Tests

```bash
# Run tests
pytest tests/ -v

# Run tests with coverage
pytest tests/ -v --cov=netlogo_mcp --cov-report=term-missing
```

Tests use mock fixtures — no Java/NetLogo installation needed to run them.

For a live end-to-end check against a real NetLogo install (lazy JVM boot,
widget XML acceptance, protocol resilience after NetLogo errors):

```bash
python tests/manual_smoke.py   # headless; needs NETLOGO_HOME in env or .env
```

## Linting & Formatting

```bash
# Check lint
ruff check src/ tests/

# Auto-format
ruff format src/ tests/

# Type check
mypy src/netlogo_mcp/
```

Pre-commit hooks (installed via `pre-commit install`) will run these automatically.

## Architecture Notes

### Stdout Protection
The MCP stdio transport uses stdout for JSON-RPC, and two writers can corrupt it:

1. **The JVM** — `System.out` writes to OS-level fd 1 directly, bypassing Python's `sys.stdout` entirely. Python-level redirection can never protect against this.
2. **pynetlogo** — it `print()`s Java stack traces to `sys.stdout` whenever a NetLogo command/reporter/load fails.

`main()` neutralizes both before serving: fd 1 is `os.dup`'d and the private copy handed to the transport through a `_HybridStdout` object (`sys.stdout.buffer` → protocol fd for the transport; text-level `write()` → stderr for prints), then fd 1 is re-pointed at stderr with `os.dup2(2, 1)`. The lifespan must NOT touch `sys.stdout` — FastMCP 3 enters the lifespan *before* binding the stdio transport.

### Stdin Protection (Windows JVM deadlock)
The transport keeps a pending blocking read on the stdin pipe from a worker thread. Windows serializes operations on a synchronous pipe's file object — while that read is pending, even metadata probes (`GetFileType`) on the same pipe block. The JVM probes the standard handles during `CreateJavaVM`, so lazy JVM startup deadlocked until the client happened to send a byte. `main()` therefore also privatizes stdin: the transport reads a duplicate handle, while fd 0 and the Win32 `STD_INPUT_HANDLE` point at devnull. (This pathology is why an earlier lazy-startup attempt was abandoned for eager startup — under FastMCP 3, the eager lifespan ran before the transport started reading stdin.)

### Lazy JVM Startup
The JVM boots on the **first tool call that needs the workspace** (`open_model` / `create_model` / `open_comses_model`), via `tools._ensure_netlogo`:

- Startup runs through `asyncio.to_thread` under the workspace lock, so the event loop (and MCP heartbeats) stay responsive during the 30-60s boot. (An earlier lazy implementation blocked the event loop inside the tool call — that's why the project temporarily used eager startup. `_jvm_call`'s thread offloading removed that constraint.)
- Connecting an MCP client no longer pops a NetLogo window — it only appears when a model tool is actually used.
- Tools that don't need the JVM (`server_info`, `list_models`, CoMSES search/read, BehaviorSpace list/preview) work immediately.
- `NETLOGO_EAGER_START=true` restores boot-at-launch for users who want to pre-warm the JVM.

### Thread Safety
- `thd=False` is passed to `pynetlogo.NetLogoLink` — JPype handles the Swing EDT internally. Setting `thd=True` hangs on Windows.
- All JVM calls go through `tools._jvm_call`, which serializes them under the lifespan's `workspace_lock` and runs them via `asyncio.to_thread`. JPype attaches worker threads to the JVM automatically; the lock guarantees single-flight access to the shared workspace.
- Don't swap `sys.stdout` around individual tool calls — the permanent fd-level redirect in `main()` already covers JVM output, and per-call swapping races with other threads mid-write.

### GUI vs Headless
Controlled by the `NETLOGO_GUI` env var (defaults to `true`). With lazy startup, the GUI window doubles as visual confirmation that the first model call succeeded.

### BehaviorSpace runs in a separate JVM
The MCP server's interactive workspace stays alive while `run_experiment` spawns a fresh `NetLogo_Console --headless` (or `netlogo-headless.bat`) subprocess. Trade-offs:

- **Pro:** canonical BehaviorSpace semantics — parallel run scheduling, full table CSV format, no dependency on the unbundled `bspace` extension.
- **Pro:** the GUI workspace doesn't get clobbered — long sweeps don't kill interactive use.
- **Con:** spawning a second JVM is heavy (~30-60s per run). For one-off small sweeps, the existing `parameter_sweep` prompt (which uses the live JVM via `repeat_report`) is still cheaper.
- The setup-file XML and table CSV land in `exports/experiments/`. The XML uses the standalone `behaviorspace.dtd` DOCTYPE; the table CSV's first 6 lines are metadata and `parse_table_csv` skips them.

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md).
