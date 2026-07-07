# Configuration

Create a `.env` file in the project root (or set env vars in your MCP
client config):

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

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NETLOGO_HOME` | Yes | Path to your NetLogo installation directory |
| `JAVA_HOME` | No | Path to your JDK directory (auto-detected if not set) |
| `NETLOGO_MODELS_DIR` | No | Directory for model files (defaults to the current working directory's `./models`) |
| `NETLOGO_GUI` | No | `"true"` (default) for live GUI window, `"false"` for headless. **No effect on macOS** — see below. |
| `NETLOGO_EAGER_START` | No | `"false"` (default) — the JVM boots lazily on the first tool call that needs it. Set `"true"` to boot at server startup (pre-warms the 30-60s JVM start, but opens the NetLogo window the moment your MCP client connects). |
| `NETLOGO_EXPORTS_DIR` | No | Directory for exported views/worlds (defaults to the current working directory's `./exports`) |
| `COMSES_MAX_DOWNLOAD_MB` | No | Max CoMSES archive size in MB (default 50). Enforced mid-stream. |
| `NETLOGO_EXPORTS_MAX_FILES` | No | Max files retained in each `exports/` subdirectory (default 200). Oldest are pruned after each `export_view` / `export_world`. Set to `0` to disable. |
| `NETLOGO_MCP_RESTRICTED` | No | Set to `"true"` to block dangerous NetLogo primitives (`file-*`, `import-world`, `set-current-directory`, extension shell escapes). Off by default — see [SECURITY.md](SECURITY.md). |

## GUI vs headless mode

| Mode | `NETLOGO_GUI` | What happens |
|------|---------------|--------------|
| **Live GUI** (default) | `"true"` or omitted | Opens a NetLogo window on first use. Watch simulations run in real-time. |
| **Headless** | `"false"` | No window. Faster startup. See snapshots via `export_view` in chat. |

The mode is set at startup — to switch, change the env var and restart your
client.

### macOS: live GUI is not available

On macOS the server always runs **headless**, regardless of `NETLOGO_GUI`.
The underlying `pynetlogo` library forces headless mode on macOS (it sets
`java.awt.headless=true`), because macOS AWT/Cocoa requires windows to be
created on the process's main thread with `-XstartOnFirstThread` — which an
MCP stdio server can't cede to Swing. To reflect this honestly, `get_gui_mode`
returns `false` on macOS and `server_info` includes a `gui_unavailable_reason`
field.

The engine still runs fully: `command`, `report`, `run_simulation`, and
`export_view` all work and produce correct results/snapshots. To *watch* a
model live on macOS, open the generated `.nlogox` file (in your models
directory) in the NetLogo desktop app.

## Startup timing

The JVM (and the NetLogo window, in GUI mode) starts **lazily** — on the
first `open_model` / `create_model` / `open_comses_model` call, not when
your MCP client connects. That first call takes 30-60 seconds; everything
after is instant. Tools that don't need the JVM (`server_info`,
`list_models`, all CoMSES search/read tools, BehaviorSpace
`list_experiments` / `preview_experiment`) work immediately.

If you'd rather pay the 30-60s at client startup so the first model call is
instant, set `NETLOGO_EAGER_START=true`.
