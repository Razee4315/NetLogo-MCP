"""Hillstrom email backtest — simulated vs real outcomes by segment.

See README.md in this directory for setup (download hillstrom.csv first)
and the covariate->persona mapping rationale.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from netlogo_mcp.market.archetypes import assign_archetypes
from netlogo_mcp.market.cognition import CognitionEngine
from netlogo_mcp.market.config import get_llm_config
from netlogo_mcp.market.personas import build_network
from netlogo_mcp.market.schemas import (
    Audience,
    AudienceSpec,
    ExposureEvent,
    Persona,
)
from netlogo_mcp.market.stimulus import email_stimulus

CSV = Path(__file__).parent / "hillstrom.csv"
N_PERSONAS = 600  # sampled rows -> personas (empirical joint distribution)
SEED = 20080320

# The simulated approximation of the Womens merchandise email.
STIMULUS = email_stimulus(
    id="womens-email",
    subject="New arrivals in womens: picked for you",
    sender="The Store <news@store.example>",
    body_text=(
        "Our new womens collection just landed — dresses, knits, and "
        "accessories picked from what you've browsed before. Free shipping "
        "on orders over $50 this week."
    ),
    cta="Shop the womens collection",
    offer="free shipping over $50",
    price_shown=None,
)


def _persona_from_row(row: pd.Series, i: int, rng: np.random.Generator) -> Persona:
    """Documented covariate -> persona mapping (see README)."""
    hist = float(row["history"])
    income = "low" if hist < 100 else ("mid" if hist < 350 else "high")
    newbie = int(row["newbie"]) == 1
    womens_buyer = int(row["womens"]) == 1
    recency = float(row["recency"])  # months since last purchase (1-12)
    email_prop = float(np.clip(0.65 - 0.03 * recency + rng.normal(0, 0.08), 0.05, 0.95))
    if str(row["channel"]).lower().startswith("multi"):
        email_prop = min(0.95, email_prop + 0.10)

    def n(mean: float, sd: float) -> float:
        return float(np.clip(rng.normal(mean, sd), 0.0, 1.0))

    return Persona(
        id=f"hillstrom-{i:04d}",
        age=int(np.clip(rng.normal(42, 12), 20, 75)),
        gender="female" if womens_buyer else ("male" if int(row["mens"]) else "unspecified"),
        location=str(row["zip_code"]).replace("Surburban", "suburban").lower(),
        income_bracket=income,
        occupation="retail customer",
        category_involvement=n(0.65 if womens_buyer else 0.30, 0.15),
        price_sensitivity=n(0.7 if income == "low" else 0.5 if income == "mid" else 0.35, 0.12),
        brand_loyalty=n(0.2 if newbie else 0.55, 0.12),
        current_solution="this store, occasionally" if not newbie else "first-time buyer here",
        trust_in_ads=n(0.35, 0.12),
        channels={"email": email_prop, "paid_social": 0.4, "organic": 0.5},
        influence=n(0.35, 0.2),
        susceptibility=n(0.5, 0.15),
        persona_card=(
            f"I'm a {'first-time' if newbie else 'repeat'} customer of this "
            f"store from a {row['zip_code'].lower()} area; I bought "
            f"{'womens' if womens_buyer else 'mens' if int(row['mens']) else 'some'} "
            f"merchandise about {int(recency)} month(s) ago and have spent about "
            f"${hist:.0f} with them in the last year. "
            + ("I shop carefully and compare prices. " if income == "low" else "")
            + "Brand emails are fine when they show me things I actually buy."
        ),
    )


def _segment(row: pd.Series) -> str:
    tier = "low" if row["history"] < 100 else ("mid" if row["history"] < 350 else "high")
    return f"{str(row['zip_code']).lower()}|newbie={int(row['newbie'])}|{tier}"


async def main() -> None:
    if not CSV.is_file():
        print(f"hillstrom.csv not found at {CSV}.\n"
              "Download it first — see validation/hillstrom/README.md")
        return

    df = pd.read_csv(CSV)
    df.columns = [c.strip().lower() for c in df.columns]
    treated = df[df["segment"] == "Womens E-Mail"].reset_index(drop=True)
    print(f"dataset: {len(df)} customers, womens-email group: {len(treated)}")
    real_overall = treated["visit"].mean()

    rng = np.random.default_rng(SEED)
    sample = treated.sample(N_PERSONAS, random_state=SEED).reset_index(drop=True)
    personas = [_persona_from_row(r, i, rng) for i, r in sample.iterrows()]
    spec = AudienceSpec(
        name="hillstrom-backtest",
        product_context="womens fashion and merchandise from a store they know",
        size=len(personas),
        seed=SEED,
    )
    audience = Audience(
        spec=spec,
        personas=personas,
        edges=build_network(spec.network, personas, rng),
    )
    assign_archetypes(audience)

    cfg = get_llm_config()
    print(f"cognition: {cfg.mode}")
    engine = CognitionEngine(audience, fidelity="full", use_cache=False)
    events = [
        ExposureEvent(agent_index=i, exposure_type="direct", tick=1)
        for i in range(audience.size)
    ]
    decisions = await engine.decide_batch(events, STIMULUS)

    # 'visit' in the dataset = visited the site within 2 weeks of the email.
    # Simulated analogue: opened AND (clicked / saved / bought / shared).
    sim_visit = {
        d.agent_index: d.state in ("clicked", "converted")
        for d in decisions
    }

    # Segment-level comparison.
    rows = []
    for i, r in sample.iterrows():
        rows.append(
            {"segment": _segment(r), "real_visit": r["visit"],
             "sim_visit": int(sim_visit.get(i, False))}
        )
    seg = (
        pd.DataFrame(rows)
        .groupby("segment")
        .agg(n=("real_visit", "size"), real=("real_visit", "mean"),
             sim=("sim_visit", "mean"))
        .query("n >= 20")
        .sort_values("real", ascending=False)
    )
    print(f"\nsimulated overall visit-rate: {np.mean(list(sim_visit.values())):.1%} "
          f"(raw, uncalibrated) | real: {real_overall:.1%}")
    print(f"\nsegments (n>=20):\n{seg.round(3).to_string()}")

    from scipy.stats import spearmanr

    rho, p = spearmanr(seg["real"], seg["sim"])
    print("\n--- VERDICT ---")
    print(f"segment-ranking Spearman rho = {rho:.3f} (p={p:.3f}, "
          f"{len(seg)} segments)")
    print(f"[{'PASS' if rho > 0.4 else 'FAIL'}] directional segment agreement (rho > 0.4)")
    print("Note: absolute rates need `calibrate`; ranking is the primary claim.")


if __name__ == "__main__":
    asyncio.run(main())
