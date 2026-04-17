# MCP Client Setup

NetLogo MCP uses the **MCP stdio transport**, supported by all major AI coding tools. Pick your tool below.

All examples use Windows paths — adjust for your OS:
- **macOS:** `NETLOGO_HOME=/Applications/NetLogo 7.0.3`, `JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home`
- **Linux:** `NETLOGO_HOME=/opt/netlogo-7.0.3`, `JAVA_HOME=/usr/lib/jvm/java-21-openjdk`

---

## Claude Code

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

Restart Claude Code and verify with `/mcp`.

---

## Claude Desktop

Add to `claude_desktop_config.json`:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

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

---

## Cursor

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

---

## VS Code (Copilot)

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

> **Note:** VS Code uses `"servers"` instead of `"mcpServers"`.

---

## Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

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

---

## Cline

Add via Cline settings UI, or edit `cline_mcp_settings.json`:

```json
{
  "mcpServers": {
    "netlogo": {
      "command": "netlogo-mcp",
      "args": [],
      "env": {
        "NETLOGO_HOME": "C:/Program Files/NetLogo 7.0.3",
        "JAVA_HOME": "C:/Program Files/Eclipse Adoptium/jdk-25.0.2.10-hotspot"
      },
      "disabled": false
    }
  }
}
```

---

## Roo Code

Add to `.roo/mcp.json` (project) or via VS Code settings:

```json
{
  "mcpServers": {
    "netlogo": {
      "command": "netlogo-mcp",
      "args": [],
      "env": {
        "NETLOGO_HOME": "C:/Program Files/NetLogo 7.0.3",
        "JAVA_HOME": "C:/Program Files/Eclipse Adoptium/jdk-25.0.2.10-hotspot"
      },
      "disabled": false
    }
  }
}
```

---

## Continue

Create `.continue/mcpServers/netlogo.json`:

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

> **Note:** MCP tools only work in Continue's Agent mode.

---

## Zed

Add to Zed `settings.json`:

```json
{
  "context_servers": {
    "netlogo": {
      "command": {
        "path": "netlogo-mcp",
        "args": [],
        "env": {
          "NETLOGO_HOME": "C:/Program Files/NetLogo 7.0.3",
          "JAVA_HOME": "C:/Program Files/Eclipse Adoptium/jdk-25.0.2.10-hotspot"
        }
      }
    }
  }
}
```

> **Note:** Zed uses `"context_servers"` with a nested `"command"` object.

---

## OpenCode

Add to `opencode.json` (project root) or `~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "netlogo": {
      "type": "local",
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

> **Note:** OpenCode uses `"mcp"` as the root key and `"type": "local"` for stdio.

---

## Codex (OpenAI)

Add to your Codex MCP configuration (typically `codex.json` or via the Codex CLI config):

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

> **Note:** Codex runs MCP servers as stdio subprocesses. Make sure `netlogo-mcp` is on your PATH (installed via `pip install -e .`).
