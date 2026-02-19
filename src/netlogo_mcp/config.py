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
        raise EnvironmentError(
            "NETLOGO_HOME is not set. "
            "Set it to your NetLogo installation directory, "
            "e.g. C:/Program Files/NetLogo 6.4.0"
        )
    p = Path(val)
    if not p.is_dir():
        raise EnvironmentError(
            f"NETLOGO_HOME points to a directory that does not exist: {val}"
        )
    return str(p)


def get_jvm_path() -> str:
    """Return the path to jvm.dll (or libjvm.so), derived from JAVA_HOME."""
    java_home = os.environ.get("JAVA_HOME", "")
    if not java_home:
        return ""  # let JPype use its default

    p = Path(java_home)
    # Standard locations for jvm library
    candidates = [
        p / "bin" / "server" / "jvm.dll",       # Windows
        p / "lib" / "server" / "libjvm.so",      # Linux
        p / "lib" / "server" / "libjvm.dylib",   # macOS
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
