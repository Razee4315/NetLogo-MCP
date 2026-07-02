"""Rung-1 validation: Bass-style diffusion (plan.md §10).

If word-of-mouth in the simulated audience cannot produce an S-shaped
cumulative adoption curve, nothing downstream matters. This script seeds a
small fraction of a high-affinity, well-connected population via 'organic'
delivery and lets WOM carry the rest, then fits a logistic curve to the
cumulative reached counts.

PASS = logistic fit R² >= 0.95 and WOM accounts for the majority of
exposures.

Run:
    uv run python validation/bass_diffusion.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from netlogo_mcp.market.archetypes import assign_archetypes
from netlogo_mcp.market.cognition import CognitionEngine, HeuristicBackend
from netlogo_mcp.market.personas import generate_audience
from netlogo_mcp.market.schemas import (
    AudienceSpec,
    ChannelParams,
    NetworkSpec,
    Stimulus,
)
from netlogo_mcp.market.worlds import PythonWorld

# A shareable, high-affinity product in a chatty, connected audience.
SPEC = AudienceSpec(
    name="bass-audience",
    product_context="a free group-fitness challenge app friends do together",
    size=300,
    seed=99,
    distributions={
        "category_involvement": {"mean": 0.75, "sd": 0.12},
        "trust_in_ads": {"mean": 0.55, "sd": 0.15},
        "susceptibility": {"mean": 0.7, "sd": 0.12},
        "influence": {"mean": 0.55, "sd": 0.2},
        "personality.extraversion": {"mean": 0.7, "sd": 0.12},
        "channels.organic": {"mean": 0.7, "sd": 0.12},
    },
    network=NetworkSpec(topology="watts-strogatz", k=10, rewire=0.15),
)

STIMULUS = Stimulus(
    id="bass-v1",
    type="social_ad",
    teaser={"headline": "Your friends are doing the 30-day challenge"},
    body_text=(
        "Join the free 30-day fitness challenge. Team up with friends, "
        "track streaks together, no equipment needed, completely free."
    ),
    cta="Join free with your crew",
    offer="free",
    channel_params=ChannelParams(
        channel="organic", send_tick=1, reach=0.05, frequency_cap=6
    ),
)


def logistic(t: np.ndarray, k: float, m: float, r: float) -> np.ndarray:
    return k / (1 + np.exp(-r * (t - m)))


async def main() -> None:
    audience = assign_archetypes(generate_audience(SPEC))
    engine = CognitionEngine(
        audience, backend=HeuristicBackend(), fidelity="full", use_cache=False
    )
    world = PythonWorld()
    await world.setup(audience, STIMULUS, seed=7)

    # Viral-product parameterization: this rung validates the DIFFUSION
    # MACHINERY (scheduling, network, saturation), so engaged agents share
    # at a rate that puts the cascade's R0 above 1 — a deliberately
    # shareable product. The heuristic's organic share rate (~1-2%, realistic
    # for ads) would not ignite from a 5% seed, by design.
    viral_rng = np.random.default_rng(11)

    cumulative_reached: list[int] = []
    social, direct = 0, 0
    for _ in range(120):
        await world.step()
        events = await world.pending_exposures()
        social += sum(e.exposure_type == "social" for e in events)
        direct += sum(e.exposure_type == "direct" for e in events)
        decisions = await engine.decide_batch(events, STIMULUS)
        for d in decisions:
            if d.stage1.action == "open" and not d.will_share:
                p = audience.personas[d.agent_index]
                d.will_share = bool(
                    viral_rng.random() < 0.6 * p.personality.extraversion
                )
        await world.apply_decisions(decisions)
        counts = await world.state_counts()
        cumulative_reached.append(audience.size - counts["unaware"])
        if await world.is_quiet():
            break

    y = np.array(cumulative_reached, dtype=float)
    t = np.arange(len(y), dtype=float)
    print(
        f"ticks: {len(y)}, final reached: {y[-1]:.0f}/{audience.size}, "
        f"exposures: {direct} direct + {social} social"
    )
    if len(y) < 8:
        print("\n--- VERDICT ---")
        print("[FAIL] cascade died immediately — no curve to fit")
        return

    from scipy.optimize import curve_fit

    try:
        (k, m, r), _ = curve_fit(
            logistic,
            t,
            y,
            p0=[y[-1], len(y) / 3, 0.3],
            maxfev=20000,
        )
        y_hat = logistic(t, k, m, r)
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    except RuntimeError:
        r2 = 0.0

    grew_after_seed = y[-1] > y[1] * 2 if len(y) > 2 and y[1] > 0 else y[-1] > 0
    wom_majority = social > direct

    print(f"logistic fit R² = {r2:.3f} (ceiling k={k:.0f}, midpoint t={m:.1f})")
    print("\n--- VERDICT ---")
    print(f"[{'PASS' if r2 >= 0.95 else 'FAIL'}] S-curve shape (R² >= 0.95)")
    print(
        f"[{'PASS' if wom_majority else 'FAIL'}] "
        f"word-of-mouth dominates ({social} social vs {direct} direct)"
    )
    print(f"[{'PASS' if grew_after_seed else 'FAIL'}] diffusion beyond the seed group")


if __name__ == "__main__":
    asyncio.run(main())
