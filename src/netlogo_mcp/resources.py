"""NetLogo MCP resources — documentation and model source access."""

from __future__ import annotations

from pathlib import Path

from fastmcp.exceptions import ToolError

from .config import get_models_dir
from .server import mcp

_DATA_DIR = Path(__file__).resolve().parent / "data"


@mcp.resource("netlogo://docs/primitives")
def primitives_reference() -> str:
    """NetLogo primitives quick reference — commands, reporters, and syntax."""
    return (_DATA_DIR / "primitives.md").read_text(encoding="utf-8")


@mcp.resource("netlogo://docs/programming")
def programming_guide() -> str:
    """NetLogo programming guide — contexts, breeds, variables, control flow."""
    return (_DATA_DIR / "programming_guide.md").read_text(encoding="utf-8")


@mcp.resource("netlogo://models/{name}")
def model_source(name: str) -> str:
    """Return the source code of a .nlogo/.nlogox model from the models directory.

    Args:
        name: Model filename (with or without extension).
              Accepts .nlogo and .nlogox files.
    """
    if ".." in name or "/" in name or "\\" in name:
        raise ToolError("Invalid model name (path traversal not allowed).")

    models_dir = get_models_dir().resolve()

    # If the name already has a recognized extension, use it directly
    if name.endswith((".nlogo", ".nlogox")):
        model_path = (models_dir / name).resolve()
    else:
        # Try .nlogo first, then .nlogox
        model_path = (models_dir / f"{name}.nlogo").resolve()
        if not model_path.exists():
            model_path = (models_dir / f"{name}.nlogox").resolve()

    # Ensure resolved path is still inside models dir
    if not model_path.is_relative_to(models_dir):
        raise ToolError("Invalid model name (path traversal not allowed).")

    if not model_path.exists():
        raise ToolError(f"Model not found: {name}")

    return model_path.read_text(encoding="utf-8")
