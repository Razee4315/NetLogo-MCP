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
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from threading import Lock
from typing import Any, Callable, TypeVar

from fastmcp import FastMCP

from .config import get_gui_mode, get_jvm_path, get_netlogo_home

logger = logging.getLogger("netlogo_mcp")
_workspace_lock = Lock()
T = TypeVar("T")


@contextmanager
def protect_stdout() -> Iterator[None]:
    """Temporarily redirect stdout to stderr during JVM/NetLogo operations."""
    previous_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = previous_stdout


def run_with_stdout_protection(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run a callable while shielding MCP stdout from JVM output."""
    with protect_stdout():
        return func(*args, **kwargs)


def get_or_create_netlogo(lifespan_context: dict[str, Any]) -> Any:
    """Create the shared NetLogo workspace on first use, then reuse it."""
    existing = lifespan_context.get("netlogo")
    if existing is not None:
        return existing

    with _workspace_lock:
        existing = lifespan_context.get("netlogo")
        if existing is not None:
            return existing

        # Deferred import — JVM must not start at module import time
        with protect_stdout():
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

        lifespan_context["netlogo"] = nl
        logger.info("NetLogo workspace ready (%s)", mode_str)
        return nl


def shutdown_netlogo(lifespan_context: dict[str, Any]) -> None:
    """Close the shared NetLogo workspace if it was created."""
    nl = lifespan_context.pop("netlogo", None)
    if nl is None:
        return

    logger.info("Shutting down NetLogo workspace")
    try:
        run_with_stdout_protection(nl.kill_workspace)
    except Exception:
        logger.exception("Failed to shut down NetLogo workspace cleanly")


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Keep shared lifecycle state; start NetLogo lazily on first tool use."""
    state: dict[str, Any] = {}
    try:
        yield state
    finally:
        shutdown_netlogo(state)


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
