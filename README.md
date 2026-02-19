<p align="center">
  <img src="https://upload.wikimedia.org/wikipedia/en/thumb/d/df/NetLogo_Logo_%28no_text%29.svg/1200px-NetLogo_Logo_%28no_text%29.svg.png" width="80" alt="NetLogo MCP Logo">
  <h1 align="center">NetLogo MCP</h1>
</p>

The first MCP (Model Context Protocol) server for NetLogo — enabling AI assistants like Claude to create, run, and analyze agent-based models through natural conversation.

## Why NetLogo MCP?

As an AI student in my 6th semester, I was taking an Agent-Based Modeling course that heavily uses NetLogo. When I discovered MCP (Model Context Protocol) and how it lets AI assistants interact with external tools, I immediately searched for a NetLogo MCP server. Nothing existed — not for NetLogo, not for any agent-based modeling platform.

So I built one.

The idea is simple: instead of manually writing NetLogo code, clicking buttons, and tweaking sliders, you just tell Claude what you want in plain English. "Create a predator-prey model with 100 sheep and 20 wolves." "Run it for 500 ticks and show me the population dynamics." "What happens if we double the wolf reproduction rate?" Claude handles the code, runs the simulation, and shows you the results — all through conversation.

This bridges the gap between AI-powered assistance and agent-based modeling, making NetLogo accessible to anyone who can describe what they want to simulate.

## How It Works

```
You (in Claude Code) → Claude → MCP Protocol → NetLogo MCP Server → NetLogo (headless JVM)
```

The server runs NetLogo in headless mode (no GUI) as a background Java process. Claude sends commands through the MCP protocol, NetLogo executes them, and results come back — including simulation data, agent counts, and exported view snapshots you can see right in the chat.

## Features

- **Create Models from Code** — Write NetLogo procedures, Claude wraps them in the proper format and loads them
- **Run Simulations** — Execute setup, go, or any custom command with full control
- **Collect Data** — Run N ticks and collect reporter data as markdown tables
- **Visual Snapshots** — Export the current world view as PNG images, visible inline in chat
- **Parameter Control** — Set globals, sliders, and switches programmatically
- **World Inspection** — Get tick counts, agent counts, world dimensions, and patch data grids
- **Model Library** — Browse and load `.nlogo`/`.nlogox` files from a models directory
- **Built-in References** — NetLogo primitives and programming guide as MCP resources
- **Prompt Templates** — Pre-built workflows for model analysis, ABM creation, and parameter sweeps

## Tools

| Tool | Description |
|------|-------------|
| `create_model(code)` | Create a new model from NetLogo code |
| `open_model(path)` | Load an existing .nlogo/.nlogox model |
| `command(netlogo_command)` | Execute a NetLogo command (setup, go, etc.) |
| `report(reporter)` | Evaluate a reporter expression |
| `run_simulation(ticks, reporters)` | Run N ticks, collect data as a table |
| `set_parameter(name, value)` | Set a global variable / slider / switch |
| `get_world_state()` | Get tick count, agent counts, world dimensions |
| `get_patch_data(attribute)` | Get patch data as a 2D grid (for heatmaps) |
| `export_view()` | Export current view as PNG image |
| `save_model(name, code)` | Save model to file — open in NetLogo app for live viewing |
| `export_world()` | Export full world state to CSV for offline analysis |
| `list_models()` | List model files in models directory |

## Resources

| URI | Description |
|-----|-------------|
| `netlogo://docs/primitives` | NetLogo primitives quick reference |
| `netlogo://docs/programming` | NetLogo programming guide |
| `netlogo://models/{name}` | Read model source code |

## Prompts

| Prompt | Description |
|--------|-------------|
| `analyze_model(model_name)` | Step-by-step guide to understand an existing model |
| `create_abm(description, agents, behaviors)` | Build a new ABM from scratch |
| `parameter_sweep(parameter, min, max, steps, metric)` | Systematic parameter exploration |

## Prerequisites

- **Python 3.10+**
- **Java JDK 11+** — [Adoptium Temurin](https://adoptium.net/) recommended
- **NetLogo 7.0+** — [Download](https://ccl.northwestern.edu/netlogo/download.shtml)

## Installation

```bash
# Clone the repository
git clone https://github.com/Razee4315/NetLogo_MCP.git
cd NetLogo_MCP

# Install the package
pip install -e ".[dev]"
```

## Configuration

Copy `.env.example` to `.env` and set your paths:

```env
NETLOGO_HOME=C:/Program Files/NetLogo 7.0.3
JAVA_HOME=C:/Program Files/Eclipse Adoptium/jdk-25.0.2.10-hotspot
```

### Claude Code Integration

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "netlogo": {
      "command": "netlogo-mcp",
      "args": [],
      "env": {
        "NETLOGO_HOME": "C:/Program Files/NetLogo 7.0.3",
        "JAVA_HOME": "C:/Program Files/Eclipse Adoptium/jdk-25.0.2.10-hotspot",
        "NETLOGO_MODELS_DIR": "C:/path/to/NetLogo_MCP/models"
      }
    }
  }
}
```

Then restart Claude Code. Verify with `/mcp` — the netlogo server should appear with 10 tools.

## Quick Start

Once connected, try these in Claude Code:

```
> Create a simple NetLogo model with 50 turtles doing a random walk.
  Run setup, simulate 100 ticks, and export the view.

> Open the Wolf Sheep Predation model and run a parameter sweep
  on initial-number-wolves from 10 to 100.

> Build a disease spread model with susceptible, infected, and
  recovered agents on a grid.
```

## Tech Stack

- **Server**: [FastMCP](https://gofastmcp.com/) (Python)
- **NetLogo Bridge**: [pynetlogo](https://github.com/quaquel/pynetlogo) + [JPype](https://github.com/jpype-project/jpype)
- **Runtime**: NetLogo headless JVM
- **Transport**: MCP stdio protocol

## Project Structure

```
NetLogo_MCP/
├── pyproject.toml              # Package config & dependencies
├── .mcp.json                   # Claude Code MCP configuration
├── src/
│   └── netlogo_mcp/
│       ├── server.py           # FastMCP app, stdout protection, lifespan
│       ├── tools.py            # All 10 tools
│       ├── resources.py        # 3 resources (docs + model source)
│       ├── prompts.py          # 3 prompts (analyze, create, sweep)
│       ├── config.py           # Environment variable loading
│       └── data/
│           ├── primitives.md   # NetLogo primitives reference
│           └── programming_guide.md
├── models/                     # Drop .nlogo/.nlogox files here
└── tests/
    ├── conftest.py             # Mock fixtures (no JVM needed)
    ├── test_tools.py
    └── test_resources.py
```

## Running Tests

```bash
pytest tests/ -v
```

Tests use mock fixtures — no Java/NetLogo installation needed to run them.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `NETLOGO_HOME is not set` | Set the environment variable to your NetLogo install directory |
| `JAVA_HOME is not set` | Set it to your JDK directory (not JRE) |
| JVM crashes on startup | Make sure JAVA_HOME points to JDK 11+, not an older version |
| `No model is loaded` | Call `open_model` or `create_model` before using other tools |
| NetLogo syntax errors | Consult the `netlogo://docs/primitives` resource |
| Server won't connect | Run `netlogo-mcp` manually in terminal to see error output |

## Contributing

Contributions are welcome! This is an open project — feel free to open issues, suggest features, or submit pull requests.

## Author

**Saqlain Abbas**
Email: saqlainrazee@gmail.com
GitHub: [@Razee4315](https://github.com/Razee4315)
LinkedIn: [@saqlainrazee](https://www.linkedin.com/in/saqlainrazee/)

## License

This project is **source available** with restricted commercial use:
- **Personal use** — Free to use, copy, and modify
- **Commercial use** — Requires written permission from the author

See the [LICENSE](LICENSE) file for full details.
