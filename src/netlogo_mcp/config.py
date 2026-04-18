"""Configuration loading from environment variables.

No JVM or pynetlogo imports here — this module must be safe to import
at any time without triggering JVM startup.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def get_netlogo_home() -> str:
    """Return NETLOGO_HOME path, validated."""
    val = os.environ.get("NETLOGO_HOME", "")
    if not val:
        raise OSError(
            "NETLOGO_HOME is not set. "
            "Set it to your NetLogo installation directory, "
            "e.g. C:/Program Files/NetLogo 6.4.0"
        )
    p = Path(val)
    if not p.is_dir():
        raise OSError(f"NETLOGO_HOME points to a directory that does not exist: {val}")
    return str(p)


def get_jvm_path() -> str:
    """Return the path to jvm.dll (or libjvm.so), derived from JAVA_HOME."""
    java_home = os.environ.get("JAVA_HOME", "")
    if not java_home:
        return ""  # let JPype use its default

    p = Path(java_home)
    # Standard locations for jvm library
    candidates = [
        p / "bin" / "server" / "jvm.dll",  # Windows
        p / "lib" / "server" / "libjvm.so",  # Linux
        p / "lib" / "server" / "libjvm.dylib",  # macOS
    ]
    for c in candidates:
        if c.exists():
            return str(c)

    # Fallback: return empty and let JPype find it
    return ""


def get_models_dir() -> Path:
    """Return the directory where .nlogo model files are stored."""
    val = os.environ.get(
        "NETLOGO_MODELS_DIR",
        str(Path(__file__).resolve().parent.parent.parent / "models"),
    )
    p = Path(val)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_gui_mode() -> bool:
    """Return True if the server should launch with a live NetLogo GUI window.

    Defaults to GUI mode (True) so new users see simulations running.
    Power users can set NETLOGO_GUI=false for headless operation.
    """
    val = os.environ.get("NETLOGO_GUI", "true").lower()
    return val not in ("false", "0", "no")


def get_comses_max_download_mb() -> float:
    """Max size of a COMSES archive download, in megabytes.

    Enforced at stream time (per-byte), not just via HEAD. Default 50 MB.
    """
    val = os.environ.get("COMSES_MAX_DOWNLOAD_MB", "50")
    try:
        return max(1.0, float(val))
    except ValueError:
        return 50.0


def get_comses_cache_dir() -> Path:
    """Directory for downloaded/extracted COMSES archives."""
    models_dir = get_models_dir()
    p = models_dir / "comses"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_exports_dir() -> Path:
    """Return the directory where exported images and worlds are saved."""
    val = os.environ.get(
        "NETLOGO_EXPORTS_DIR",
        str(Path(__file__).resolve().parent.parent.parent / "exports"),
    )
    p = Path(val)
    (p / "views").mkdir(parents=True, exist_ok=True)
    (p / "worlds").mkdir(parents=True, exist_ok=True)
    return p
