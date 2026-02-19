"""NetLogo MCP Server — entry point.

CRITICAL: stdout is redirected to stderr *before* any JVM-touching import.
MCP stdio transport uses stdout for JSON-RPC messages; JPype/JVM writes to
stdout by default, which would corrupt the protocol.
"""

import sys

# ── Stdout protection — must happen before ANY JVM-related import ──
_real_stdout = sys.stdout
sys.stdout = sys.stderr

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from .config import get_gui_mode, get_jvm_path, get_netlogo_home

logger = logging.getLogger("netlogo_mcp")


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Start the JVM + NetLogo workspace once, share it for all tool calls."""
    # Deferred import — JVM must not start at module import time
    import pynetlogo

    nl_home = get_netlogo_home()
    jvm_path = get_jvm_path()
    gui = get_gui_mode()

    mode_str = "GUI (live window)" if gui else "headless"
    logger.info(
        "Starting NetLogo workspace in %s mode (NETLOGO_HOME=%s)",
        mode_str,
        nl_home,
    )
    nl = pynetlogo.NetLogoLink(
        netlogo_home=nl_home,
        gui=gui,
        thd=False,
        jvm_path=jvm_path,
    )
    logger.info("NetLogo workspace ready (%s)", mode_str)

    try:
        yield {"netlogo": nl}
    finally:
        logger.info("Shutting down NetLogo workspace")
        try:
            nl.kill_workspace()
        except Exception:
            pass


mcp = FastMCP(
    "NetLogo MCP Server",
    instructions=(
        "This server lets you create, run, and analyze NetLogo agent-based "
        "models. Use open_model or create_model first, then command/report "
        "to interact. Consult netlogo://docs/primitives for syntax help."
    ),
    lifespan=lifespan,
)

# ── Register tools, resources, and prompts ──
from . import prompts as _prompts  # noqa: E402, F401
from . import resources as _resources  # noqa: E402, F401
from . import tools as _tools  # noqa: E402, F401


def main() -> None:
    """Console-script entry point (stdio transport)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    # Restore real stdout for FastMCP's stdio transport
    sys.stdout = _real_stdout
    mcp.run()


if __name__ == "__main__":
    main()
