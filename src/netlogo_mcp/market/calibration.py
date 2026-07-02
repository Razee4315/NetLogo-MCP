"""Calibration — map raw simulated funnel rates to real-world levels.

The LLM (or heuristic) population provides *relative* discrimination — which
variant wins, which segment responds. Absolute levels are systematically off
(synthetic audiences over-engage). Calibration corrects the levels with a
logit-linear map per channel per funnel stage:

    logit(p_cal) = a + b * logit(p_raw)

- Identity (a=0, b=1) until calibrated.
- ``fit_to_base_rates`` anchors the sim's observed rates to industry
  benchmark floors (shipped in ``data/market/base_rates.json``).
- ``fit_from_observations`` fits a and b from one or more (simulated, real)
  rate pairs — e.g. a past campaign's actual stats via ``calibrate``.

Reports always show BOTH raw and calibrated numbers, clearly labeled.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np

from .config import get_market_data_dir

STAGES = ("gate", "click", "convert")

_EPS = 1e-4


def _logit(p: float) -> float:
    p = min(1 - _EPS, max(_EPS, p))
    return float(np.log(p / (1 - p)))


def _sigmoid(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-x)))


def load_base_rates() -> dict[str, dict[str, float]]:
    """Benchmark rates shipped with the package."""
    text = (
        resources.files("netlogo_mcp")
        .joinpath("data/market/base_rates.json")
        .read_text(encoding="utf-8")
    )
    data = json.loads(text)
    return {k: v for k, v in data.items() if not k.startswith("_")}


class Calibration:
    """Per-channel, per-stage logit-linear maps. Persisted as JSON."""

    def __init__(self, maps: dict[str, dict[str, dict[str, float]]] | None = None):
        # maps[channel][stage] = {"a": float, "b": float}
        self.maps = maps or {}

    # ── application ─────────────────────────────────────────────────────────

    def apply(self, channel: str, stage: str, p_raw: float) -> float:
        m = self.maps.get(channel, {}).get(stage)
        if m is None:
            return float(p_raw)
        return _sigmoid(m["a"] + m["b"] * _logit(p_raw))

    def apply_funnel(
        self, channel: str, rates: dict[str, float]
    ) -> dict[str, float]:
        return {
            stage: self.apply(channel, stage, p)
            for stage, p in rates.items()
        }

    def is_identity(self) -> bool:
        return not self.maps

    # ── fitting ──────────────────────────────────────────────────────────────

    def fit_stage(
        self, channel: str, stage: str, pairs: list[tuple[float, float]]
    ) -> None:
        """Fit a,b from (simulated_rate, real_rate) pairs on the logit scale.

        One pair pins the intercept (b=1); two or more fit the slope too.
        """
        pairs = [(s, r) for s, r in pairs if 0 < s < 1 and 0 < r < 1]
        if not pairs:
            raise ValueError(f"no usable pairs for {channel}/{stage}")
        xs = np.array([_logit(s) for s, _ in pairs])
        ys = np.array([_logit(r) for _, r in pairs])
        if len(pairs) == 1:
            b, a = 1.0, float(ys[0] - xs[0])
        else:
            b, a = np.polyfit(xs, ys, 1)
            b = float(min(3.0, max(0.2, b)))  # keep the map monotone and sane
            a = float(a)
        self.maps.setdefault(channel, {})[stage] = {"a": a, "b": b}

    def fit_to_base_rates(
        self, channel: str, simulated: dict[str, float]
    ) -> None:
        """Anchor each observed simulated stage rate to the benchmark rate."""
        base = load_base_rates().get(channel)
        if base is None:
            raise ValueError(f"no base rates for channel {channel!r}")
        for stage in STAGES:
            if stage in simulated and 0 < simulated[stage] < 1:
                self.fit_stage(channel, stage, [(simulated[stage], base[stage])])

    def fit_from_observations(
        self,
        channel: str,
        observations: list[dict[str, float]],
    ) -> None:
        """Fit from real-campaign records.

        Each observation: ``{"stage": "gate"|"click"|"convert",
        "simulated": 0.42, "real": 0.28}``.
        """
        by_stage: dict[str, list[tuple[float, float]]] = {}
        for obs in observations:
            stage = str(obs["stage"])
            if stage not in STAGES:
                raise ValueError(f"unknown stage {stage!r}; use one of {STAGES}")
            by_stage.setdefault(stage, []).append(
                (float(obs["simulated"]), float(obs["real"]))
            )
        for stage, pairs in by_stage.items():
            self.fit_stage(channel, stage, pairs)

    # ── persistence ──────────────────────────────────────────────────────────

    @staticmethod
    def _default_path() -> Path:
        return get_market_data_dir() / "calibration.json"

    def save(self, path: str | None = None) -> str:
        p = Path(path) if path else self._default_path()
        p.write_text(json.dumps(self.maps, indent=1), encoding="utf-8")
        return str(p)

    @classmethod
    def load(cls, path: str | None = None) -> Calibration:
        p = Path(path) if path else cls._default_path()
        if not p.is_file():
            return cls()  # identity
        return cls(json.loads(p.read_text(encoding="utf-8")))


def fit_from_csv(
    csv_path: str, channel: str, simulated: dict[str, float]
) -> Calibration:
    """Convenience: fit calibration from a past campaign's stats CSV.

    Expected columns (one or more rows): ``sent, opened, clicked, converted``.
    Rates are computed as opened/sent, clicked/opened, converted/clicked and
    paired against the provided simulated rates for the same funnel.
    """
    import pandas as pd

    df = pd.read_csv(csv_path)
    required = {"sent", "opened", "clicked", "converted"}
    missing = required - set(c.lower() for c in df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {sorted(missing)}")
    df.columns = [c.lower() for c in df.columns]
    totals = df[["sent", "opened", "clicked", "converted"]].sum()
    real = {
        "gate": float(totals["opened"] / max(1, totals["sent"])),
        "click": float(totals["clicked"] / max(1, totals["opened"])),
        "convert": float(totals["converted"] / max(1, totals["clicked"])),
    }
    cal = Calibration.load()
    obs: list[dict[str, Any]] = [
        {"stage": stage, "simulated": simulated[stage], "real": real[stage]}
        for stage in STAGES
        if stage in simulated and 0 < real.get(stage, 0) < 1
    ]
    if not obs:
        raise ValueError(
            "nothing to fit — provide simulated rates for gate/click/convert"
        )
    cal.fit_from_observations(channel, obs)
    cal.save()
    return cal
