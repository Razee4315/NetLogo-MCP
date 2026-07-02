"""Configuration for the market-simulation module.

Env-driven, mirroring the core ``netlogo_mcp.config`` style. No JVM imports —
safe to import anywhere, anytime.

Environment variables
---------------------
SYNTH_DATA_DIR        Root for audiences/campaigns/runs/reports.
                      Default: ``<cwd>/market_data``.
SYNTH_LLM_MODE        ``mock`` (default) or ``live``. Mock uses a
                      deterministic persona-driven heuristic client, so the
                      whole pipeline runs end-to-end with no LLM installed.
                      Flip to ``live`` once a local model is available.
SYNTH_LLM_BASE_URL    OpenAI-compatible endpoint. Default is Ollama's:
                      ``http://localhost:11434/v1``.
SYNTH_LLM_MODEL       Model name, e.g. ``qwen3:4b``. Default: ``qwen3:4b``.
SYNTH_LLM_API_KEY     Bearer key. Ollama ignores it; cloud providers need it.
SYNTH_LLM_CONCURRENCY Max in-flight LLM requests. Default 8 (match
                      ``OLLAMA_NUM_PARALLEL``).
SYNTH_LLM_TIMEOUT     Per-request timeout in seconds. Default 120.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def get_market_data_dir() -> Path:
    """Root directory for all market-sim artifacts (created on demand)."""
    val = os.environ.get("SYNTH_DATA_DIR", str(Path.cwd() / "market_data"))
    root = Path(val)
    for sub in ("audiences", "campaigns", "runs", "reports", "cache"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def get_audiences_dir() -> Path:
    return get_market_data_dir() / "audiences"


def get_campaigns_dir() -> Path:
    return get_market_data_dir() / "campaigns"


def get_runs_dir() -> Path:
    return get_market_data_dir() / "runs"


def get_reports_dir() -> Path:
    return get_market_data_dir() / "reports"


def get_cache_dir() -> Path:
    return get_market_data_dir() / "cache"


@dataclass(frozen=True)
class LLMConfig:
    """Connection settings for the cognition engine's LLM."""

    mode: str = "mock"  # "mock" | "live"
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen3:4b"
    api_key: str = "ollama"
    concurrency: int = 8
    timeout: float = 120.0
    temperature: float = 0.9


def get_llm_config() -> LLMConfig:
    """Read LLM settings from the environment (defaults suit local Ollama)."""
    mode = os.environ.get("SYNTH_LLM_MODE", "mock").strip().lower()
    if mode not in ("mock", "live"):
        mode = "mock"

    def _num(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, default))
        except ValueError:
            return default

    return LLMConfig(
        mode=mode,
        base_url=os.environ.get(
            "SYNTH_LLM_BASE_URL", "http://localhost:11434/v1"
        ).rstrip("/"),
        model=os.environ.get("SYNTH_LLM_MODEL", "qwen3:4b"),
        api_key=os.environ.get("SYNTH_LLM_API_KEY", "ollama"),
        concurrency=max(1, int(_num("SYNTH_LLM_CONCURRENCY", 8))),
        timeout=max(5.0, _num("SYNTH_LLM_TIMEOUT", 120.0)),
        temperature=min(2.0, max(0.0, _num("SYNTH_LLM_TEMPERATURE", 0.9))),
    )
