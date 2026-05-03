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
The MCP stdio transport uses stdout for JSON-RPC. JPype/JVM writes to stdout by default, which would corrupt the protocol. `server.py` redirects stdout to stderr before any JVM import and restores it only for `mcp.run()`.

### Eager JVM Startup
The NetLogo JVM is started in the lifespan context manager (before FastMCP accepts MCP requests). This is critical because:
- Blocking the asyncio event loop inside a tool call prevents FastMCP from sending responses back.
- Starting in lifespan blocks before the protocol is active, so there's nothing to block.
- First connection takes 30-60s while the JVM warms up; every tool call after is instant.

### Thread Safety
- `thd=False` is passed to `pynetlogo.NetLogoLink` — JPype handles the Swing EDT internally. Setting `thd=True` hangs on Windows.
- The JVM's Java class loader is thread-local. All tool calls must happen on the same thread that initialized the JVM. `asyncio.to_thread` breaks this.
- Never wrap tool calls in `protect_stdout` — swapping `sys.stdout` between calls corrupts JPype's Java thread context.

### GUI vs Headless
Controlled by the `NETLOGO_GUI` env var (defaults to `true`). The GUI window serves as visual confirmation the server is running — better UX than headless-by-default.

### BehaviorSpace runs in a separate JVM
The MCP server's interactive workspace stays alive while `run_experiment` spawns a fresh `NetLogo_Console --headless` (or `netlogo-headless.bat`) subprocess. Trade-offs:

- **Pro:** canonical BehaviorSpace semantics — parallel run scheduling, full table CSV format, no dependency on the unbundled `bspace` extension.
- **Pro:** the GUI workspace doesn't get clobbered — long sweeps don't kill interactive use.
- **Con:** spawning a second JVM is heavy (~30-60s per run). For one-off small sweeps, the existing `parameter_sweep` prompt (which uses the live JVM via `repeat_report`) is still cheaper.
- The setup-file XML and table CSV land in `exports/experiments/`. The XML uses the standalone `behaviorspace.dtd` DOCTYPE; the table CSV's first 6 lines are metadata and `parse_table_csv` skips them.

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md).
