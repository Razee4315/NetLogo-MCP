<p align="center">
  <img src="logo.svg" width="250" alt="NetLogo MCP">
</p>

<p align="center">
  <a href="https://github.com/Razee4315/NetLogo-MCP/actions/workflows/ci.yml"><img src="https://github.com/Razee4315/NetLogo-MCP/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff"></a>
  <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/types-mypy-blue.svg" alt="mypy"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License"></a>
</p>

The first MCP (Model Context Protocol) server for NetLogo — enabling AI assistants to create, run, and analyze agent-based models through natural conversation.

**Works with:** Claude Code, Claude Desktop, Cursor, Windsurf, VS Code (Copilot), Cline, Continue, Roo Code, Zed, OpenCode, Codex — any tool that supports MCP.

## Why NetLogo MCP?

As an AI student taking an Agent-Based Modeling course, I searched for an MCP server to control NetLogo — nothing existed. So I built one.

Instead of manually writing NetLogo code, clicking buttons, and tweaking sliders, you tell your AI assistant what you want in plain English:

> "Create a predator-prey model with 100 sheep and 20 wolves. Run it for 500 ticks and show me the population dynamics."

The AI writes the code, runs the simulation, and shows you the results — all through conversation.

## How It Works

```
You (in any MCP client) → AI Assistant → MCP Protocol → NetLogo MCP Server → NetLogo (GUI or headless JVM)
```

By default, a real NetLogo window opens so you can watch your simulations run live. Headless mode is available for CI or servers.

## Features

- Create models from code (AI wraps them in `.nlogox` format)
- Run simulations, collect tick-by-tick data as markdown tables
- Export view as PNG — visible inline in chat
- Export plots, all plots, output logs, and full world snapshots
- Restore saved simulations with `import_world`
- Set global variables, sliders, switches
- Get world state, agent counts, world dimensions, patch grids
- Search and open bundled models from the local NetLogo Models Library
- Inspect runtime paths and workspace status with `get_server_status`
- Built-in NetLogo primitives and programming guide as MCP resources
- Prompt templates for model analysis, ABM creation, parameter sweeps
- Live GUI mode for teaching and real-time exploration

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
| `export_plot(plot_name)` | Export one plot widget to CSV |
| `export_all_plots()` | Export all plot data to CSV |
| `export_output()` | Export the output area / Command Center log |
| `export_world()` | Export full world state to CSV |
| `import_world(path)` | Restore a previously exported world snapshot |
| `save_model(name, code)` | Save model to file |
| `list_models()` | List model files in models directory |
| `search_models_library(query)` | Search the bundled local NetLogo Models Library |
| `open_library_model(path)` | Open a model from the bundled local library |
| `get_server_status()` | Show key runtime paths and workspace status |
| `search_comses(query)` | Search the CoMSES Net model library |
| `get_comses_model(uuid)` | Fetch metadata + citation text for one COMSES model |
| `download_comses_model(uuid)` | Safely download + extract a COMSES archive |
| `open_comses_model(uuid)` | Download (or reuse cache) and load NetLogo models |
| `read_comses_files(uuid)` | Read ODD / source contents from a downloaded model |

Plus 3 resources (primitives reference, programming guide, model source) and 4 prompts (`analyze_model`, `create_abm`, `parameter_sweep`, `explore_comses`).

### CoMSES Net integration

NetLogo MCP can search and safely fetch any model from the [CoMSES Net computational model library](https://www.comses.net/) — the largest peer-reviewed ABM repository. NetLogo models load automatically; Python / R / Julia models are identified and cached locally so you can inspect their source and ODD documentation from any MCP client, including clients with no filesystem tools.

Try it with the `explore_comses` prompt or just ask: *"Find me a predator-prey ABM on COMSES and run a short baseline."*

Safety properties (applied to every download):
- Archives streamed with a hard byte cap (`COMSES_MAX_DOWNLOAD_MB`, default 50 MB) enforced mid-stream, not just via HEAD.
- Every zip member is path-traversal-validated before extraction.
- Zip-bomb refusal on uncompressed-size overflow.
- Extraction is atomic: downloads land in a temp dir first, then move to the cache only on success.
- Cache directories are trusted only when they carry the `.comses_complete` marker.
- `"latest"` is resolved to a concrete version before any cache path is computed; the resolved version is returned to the AI so follow-up reads stay pinned to the same slot.

## Prerequisites

| Requirement | Install via terminal? | How |
|-------------|----------------------|-----|
| **Python 3.10+** | Yes | Windows: `winget install Python.Python.3.12` · macOS: `brew install python@3.12` · Linux: `sudo apt install python3.12` |
| **Java JDK 11+** | Yes | Windows: `winget install EclipseAdoptium.Temurin.21.JDK` · macOS: `brew install --cask temurin` · Linux: `sudo apt install openjdk-21-jdk` |
| **Git** | Yes | Windows: `winget install Git.Git` · macOS/Linux: usually pre-installed |
| **NetLogo 7.0+** | **No — manual** | Download from [ccl.northwestern.edu/netlogo](https://ccl.northwestern.edu/netlogo/download.shtml) |

> **Only NetLogo requires manual download.** Everything else can be installed via terminal, and the Zero-Config Setup prompt below handles those automatically.

## Zero-Config Setup (Recommended)

If you're using an AI coding tool, copy the prompt below into your chat. The AI will detect your OS, find your NetLogo and Java installations, clone the repo, install dependencies, configure your MCP client, and tell you how to use it.

<details open>
<summary><strong>Click to copy the setup prompt</strong></summary>

```
Please set up the NetLogo MCP server for me end-to-end. Follow these steps carefully:

1. **Detect my environment**
   - Identify my OS (Windows / macOS / Linux).
   - Check Python version (need 3.10+). If missing, tell me to install it first and stop.
   - Check for Java JDK 11+ (not JRE). Look in common locations (JAVA_HOME env var, standard install dirs). If missing, tell me to install Adoptium Temurin JDK 11+ and stop.
   - Check for NetLogo 7.0+. Look in common locations:
     - Windows: `C:/Program Files/NetLogo*`
     - macOS: `/Applications/NetLogo*`
     - Linux: `/opt/netlogo*`, `~/netlogo*`
     If NetLogo isn't installed, tell me to download it from https://ccl.northwestern.edu/netlogo/download.shtml and stop.

2. **Clone and install**
   - Pick a sensible parent directory (e.g. my home folder or `~/projects`).
   - Run: `git clone https://github.com/Razee4315/NetLogo-MCP.git`
   - `cd` into the cloned directory.
   - Run: `pip install -e .`
   - Verify the `netlogo-mcp` command is now available on my PATH.

3. **Identify my MCP client**
   - Figure out which AI tool I'm using (Claude Code, Cursor, Windsurf, Cline, Continue, Roo Code, Zed, OpenCode, VS Code Copilot, Codex, or Claude Desktop).
   - If you're not sure, ask me.

4. **Configure the MCP client**
   - Locate (or create) the correct config file for my client (see docs/CLIENTS.md for exact paths and schemas).
   - Add a `netlogo` server entry with:
     - `command`: `netlogo-mcp`
     - `env.NETLOGO_HOME`: the NetLogo path you detected
     - `env.JAVA_HOME`: the JDK path you detected
     - `env.NETLOGO_GUI`: `"true"` (default — opens a live NetLogo window)
   - Use the exact JSON schema for my specific client (e.g. `"type": "stdio"` for Cursor, `"servers"` key for VS Code).
   - Preserve any existing config entries — merge, don't overwrite.

5. **Tell me what to do next**
   - Tell me to fully restart my AI tool for the new MCP server to load.
   - Warn me that the FIRST tool call takes 30–60 seconds while the Java Virtual Machine starts (the NetLogo GUI window will appear when it's ready). Tell me NOT to click stop during this wait.
   - Give me this exact test prompt to try after restart:

     > "Create a simple predator-prey model with wolves and sheep on a green landscape. Run setup, then run 100 ticks while tracking wolf and sheep counts. Export the view before and after so I can see how the world evolved."

   - Tell me where models and exports are saved (the `models/` and `exports/` folders inside the cloned repo) and that I can browse them with the `list_models` tool.

Do not skip any verification step. If something fails, stop and tell me exactly what failed and how to fix it.
```

</details>

## Manual Installation

```bash
git clone https://github.com/Razee4315/NetLogo-MCP.git
cd NetLogo-MCP
pip install -e .
```

## Configuration

Create a `.env` file in the project root (or set env vars in your MCP client config):

```env
# Windows
NETLOGO_HOME=C:/Program Files/NetLogo 7.0.3
JAVA_HOME=C:/Program Files/Eclipse Adoptium/jdk-25.0.2.10-hotspot

# macOS
# NETLOGO_HOME=/Applications/NetLogo 7.0.3
# JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home

# Linux
# NETLOGO_HOME=/opt/netlogo-7.0.3
# JAVA_HOME=/usr/lib/jvm/java-21-openjdk
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NETLOGO_HOME` | Yes | Path to your NetLogo installation directory |
| `JAVA_HOME` | No | Path to your JDK directory (auto-detected if not set) |
| `NETLOGO_MODELS_DIR` | No | Directory for model files (defaults to `./models`) |
| `NETLOGO_GUI` | No | `"true"` (default) for live GUI window, `"false"` for headless |
| `NETLOGO_EXPORTS_DIR` | No | Directory for exported views/worlds (defaults to `./exports`) |
| `COMSES_MAX_DOWNLOAD_MB` | No | Max CoMSES archive size in MB (default 50). Enforced mid-stream. |

## Client Setup

The 3 most common clients are below. **For Windsurf, Cline, Continue, Roo Code, Zed, OpenCode, Codex, and Claude Desktop — see [docs/CLIENTS.md](docs/CLIENTS.md).**

<details>
<summary><strong>Claude Code</strong></summary>

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "netlogo": {
      "command": "netlogo-mcp",
      "args": [],
      "env": {
        "NETLOGO_HOME": "C:/Program Files/NetLogo 7.0.3",
        "JAVA_HOME": "C:/Program Files/Eclipse Adoptium/jdk-25.0.2.10-hotspot"
      }
    }
  }
}
```

Restart Claude Code and verify with `/mcp`.

</details>

<details>
<summary><strong>Cursor</strong></summary>

Add to `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "netlogo": {
      "type": "stdio",
      "command": "netlogo-mcp",
      "args": [],
      "env": {
        "NETLOGO_HOME": "C:/Program Files/NetLogo 7.0.3",
        "JAVA_HOME": "C:/Program Files/Eclipse Adoptium/jdk-25.0.2.10-hotspot"
      }
    }
  }
}
```

</details>

<details>
<summary><strong>VS Code (Copilot)</strong></summary>

Add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "netlogo": {
      "type": "stdio",
      "command": "netlogo-mcp",
      "args": [],
      "env": {
        "NETLOGO_HOME": "C:/Program Files/NetLogo 7.0.3",
        "JAVA_HOME": "C:/Program Files/Eclipse Adoptium/jdk-25.0.2.10-hotspot"
      }
    }
  }
}
```

> VS Code uses `"servers"` instead of `"mcpServers"`.

</details>

### GUI vs Headless Mode

| Mode | `NETLOGO_GUI` | What Happens |
|------|---------------|-------------|
| **Live GUI** (default) | `"true"` or omitted | Opens a NetLogo window. Watch simulations run in real-time. |
| **Headless** | `"false"` | No window. Faster startup. See snapshots via `export_view` in chat. |

The mode is set at startup — to switch, change the env var and restart your client.

## Quick Start

Once connected, try these prompts in any MCP client:

```
> Create a simple NetLogo model with 50 turtles doing a random walk.
  Run setup, simulate 100 ticks, and export the view.

> Open the Wolf Sheep Predation model and run a parameter sweep
  on initial-number-wolves from 10 to 100.

> Build a disease spread model with susceptible, infected, and
  recovered agents on a grid.
```

> **First tool call takes 30-60 seconds** while the JVM starts. Don't click stop — the NetLogo window will appear when it's ready. After that, every call is instant.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `NETLOGO_HOME is not set` | Set the environment variable to your NetLogo install directory |
| `JAVA_HOME is not set` | Set it to your JDK directory (not JRE) |
| JVM crashes on startup | Make sure JAVA_HOME points to JDK 11+, not an older version |
| `No model is loaded` | Call `open_model` or `create_model` before using other tools |
| First call hangs for 30-60s | Normal — JVM is warming up. Don't click stop. |
| Server won't connect | Run `netlogo-mcp` manually in terminal to see error output |

## Documentation

- [docs/CLIENTS.md](docs/CLIENTS.md) — Setup for all 11 MCP clients
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — Project structure, running tests, architecture notes
- [CONTRIBUTING.md](CONTRIBUTING.md) — How to contribute
- [CHANGELOG.md](CHANGELOG.md) — Version history

## Listed on

[![MCP Badge](https://lobehub.com/badge/mcp/razee4315-netlogo_mcp)](https://lobehub.com/mcp/razee4315-netlogo_mcp)

## Author

**Saqlain Abbas**
Email: saqlainrazee@gmail.com
GitHub: [@Razee4315](https://github.com/Razee4315)
LinkedIn: [@saqlainrazee](https://www.linkedin.com/in/saqlainrazee/)

## License

This project is licensed under the [MIT License](LICENSE) — free to use, modify, and distribute for any purpose.
