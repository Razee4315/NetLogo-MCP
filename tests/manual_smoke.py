"""Live end-to-end smoke test against a real NetLogo install.

Not collected by pytest (no ``test_`` prefix) — run it manually:

    python tests/manual_smoke.py

Verifies: lazy JVM boot, widget XML acceptance by NetLogo 7, slider/switch
variable wiring, and that a NetLogo error does not corrupt the MCP protocol.
Headless — no GUI window. Requires NETLOGO_HOME (and usually JAVA_HOME) in
the environment or a .env file.
"""

import asyncio
import json
import os
import sys
import tempfile

from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

load_dotenv(override=True)  # .env beats stale machine-level JAVA_HOME etc.

TMP = tempfile.mkdtemp(prefix="netlogo_mcp_smoke_")

env = dict(os.environ)
env.update(
    {
        "NETLOGO_GUI": "false",
        "NETLOGO_MODELS_DIR": os.path.join(TMP, "models"),
        "NETLOGO_EXPORTS_DIR": os.path.join(TMP, "exports"),
    }
)

transport = StdioTransport(
    sys.executable, ["-c", "from netlogo_mcp.server import main; main()"], env=env
)

CODE = """to setup
  clear-all
  create-turtles num-turtles [ setxy random-xcor random-ycor ]
  reset-ticks
end

to go
  ask turtles [ fd 1 rt random 30 ]
  tick
end"""

WIDGETS = [
    {"type": "slider", "variable": "num-turtles", "min": 1, "max": 200, "default": 50},
    {"type": "button", "code": "setup", "label": "Setup"},
    {"type": "button", "code": "go", "label": "Go", "forever": True},
    {"type": "monitor", "code": "count turtles", "label": "Turtles", "precision": 0},
    {"type": "switch", "variable": "fancy?", "default": True},
]


def text_of(result):
    return result.content[0].text


async def main():
    async with Client(transport) as client:
        # 1. server_info works pre-JVM and reports lazy state
        info = json.loads(text_of(await client.call_tool("server_info", {})))
        assert info["jvm_started"] is False, "JVM must not start at connect time"
        print("PASS 1: connected, jvm_started=False (lazy)")

        # 2. create_model with widgets — boots JVM, NetLogo must parse our XML
        r = await client.call_tool(
            "create_model", {"code": CODE, "widgets": WIDGETS}, timeout=180
        )
        print(
            "PASS 2: create_model with slider/switch/buttons/monitor:",
            text_of(r)[:80],
        )

        # 3. slider-defined global is settable; setup respects it
        await client.call_tool("set_parameter", {"name": "num-turtles", "value": 80})
        await client.call_tool("command", {"netlogo_command": "setup"})
        n = json.loads(
            text_of(await client.call_tool("report", {"reporter": "count turtles"}))
        )
        assert n == 80, f"expected 80 turtles, got {n}"
        print("PASS 3: slider variable works, setup created 80 turtles")

        # 4. switch-defined global readable
        v = json.loads(
            text_of(await client.call_tool("report", {"reporter": "fancy?"}))
        )
        assert v is True
        print("PASS 4: switch variable readable (fancy? = true)")

        # 5. intentional NetLogo error must NOT corrupt the protocol
        try:
            await client.call_tool(
                "command", {"netlogo_command": "this-is-not-a-primitive"}
            )
            raise AssertionError("expected a NetLogo error")
        except Exception as e:
            assert "NetLogo error" in str(e) or "Nothing named" in str(e), str(e)[:200]
        print("PASS 5: NetLogo error surfaced cleanly")

        # 6. protocol still alive after the error (the old stack-trace leak
        #    would have corrupted stdio here)
        n = json.loads(
            text_of(await client.call_tool("report", {"reporter": "count turtles"}))
        )
        assert n == 80
        info = json.loads(text_of(await client.call_tool("server_info", {})))
        assert info["jvm_started"] is True
        print("PASS 6: protocol healthy after error, jvm_started=True")

        # 7. run a short simulation
        table = text_of(
            await client.call_tool(
                "run_simulation", {"ticks": 10, "reporters": ["count turtles"]}
            )
        )
        assert "| tick |" in table
        print("PASS 7: run_simulation returned a 10-tick table")

    print("\nALL SMOKE TESTS PASSED")


asyncio.run(main())
