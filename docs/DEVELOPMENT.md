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
│       ├── tools.py            # All 17 tools (12 NetLogo + 5 CoMSES)
│       ├── comses.py           # CoMSES Net API client + safe zip extract
│       ├── resources.py        # 3 resources (docs + model source)
│       ├── prompts.py          # 4 prompts (analyze, create, sweep, explore_comses)
│       ├── config.py           # Environment variable loading
│       ├── py.typed            # PEP 561 type marker
│       └── data/
│           ├── primitives.md   # NetLogo primitives reference
│           └── programming_guide.md
├── models/                     # Drop your .nlogo/.nlogox files here (empty by default)
├── exports/                    # PNG views and world CSVs saved here at runtime
└── tests/
    ├── conftest.py             # Mock fixtures (no JVM needed)
    ├── test_server.py
    ├── test_tools.py
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

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md).
