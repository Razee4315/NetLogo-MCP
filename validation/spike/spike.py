"""Phase-0 feasibility spike (plan.md §12, Phase 0).

20 personas x 1 real-ish email -> reaction table. The go/no-go questions:

1. Do reactions differ meaningfully across personas?
2. Does the skeptic persona actually ignore things?
3. (live mode) Is JSON compliance > 95%? What's tokens/sec on this GPU?

Run:
    uv run python validation/spike/spike.py            # heuristic backend
    SYNTH_LLM_MODE=live uv run python validation/spike/spike.py   # Ollama

The script prints a per-persona table and a verdict summary.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from netlogo_mcp.market.archetypes import assign_archetypes
from netlogo_mcp.market.cognition import CognitionEngine
from netlogo_mcp.market.config import get_llm_config
from netlogo_mcp.market.personas import generate_audience
from netlogo_mcp.market.schemas import AudienceSpec, ExposureEvent
from netlogo_mcp.market.stimulus import email_stimulus

EMAIL = email_stimulus(
    id="spike-v1",
    subject="Dinner, solved: 3 chef-designed meals for $9",
    sender="FreshPlate <hello@freshplate.example>",
    preheader="No planning, no waste — first box discounted",
    body_text=(
        "Weeknights are chaos. FreshPlate delivers 3 chef-designed meal kits "
        "with pre-portioned ingredients to your door. Cook in 25 minutes, no "
        "planning, no waste. Skip or cancel any week. Your first box is $9 "
        "instead of $27."
    ),
    cta="Claim your $9 first box",
    offer="first box 66% off",
    price_shown="$9 first box, then $27/week",
)

SPEC = AudienceSpec(
    name="spike-audience",
    product_context="a weekly meal-kit subscription",
    size=20,
    seed=1234,
)


async def main() -> None:
    cfg = get_llm_config()
    print(
        f"cognition mode: {cfg.mode}"
        + (f" ({cfg.model} @ {cfg.base_url})" if cfg.mode == "live" else "")
    )

    audience = assign_archetypes(generate_audience(SPEC))
    engine = CognitionEngine(audience, fidelity="full", use_cache=False)

    events = [
        ExposureEvent(agent_index=i, exposure_type="direct", tick=1)
        for i in range(audience.size)
    ]
    t0 = time.time()
    decisions = await engine.decide_batch(events, EMAIL)
    elapsed = time.time() - t0

    print(
        f"\n{len(decisions)} reactions in {elapsed:.1f}s "
        f"({engine.llm_calls} cognition calls)\n"
    )
    header = (
        f"{'persona':>18} {'style':>14} {'trust':>5} {'gate':>12} {'action':>15}  why"
    )
    print(header)
    print("-" * len(header))
    for d in decisions:
        p = audience.personas[d.agent_index]
        action = d.reaction.action if d.reaction else "-"
        print(
            f"{p.id:>18} {p.objection_style:>14} {p.trust_in_ads:>5.2f} "
            f"{d.stage1.action:>12} {action:>15}  {d.verbatim[:60]}"
        )

    # ── Verdict ──────────────────────────────────────────────────────────────
    states = Counter(d.state for d in decisions)
    opens = sum(d.stage1.action == "open" for d in decisions)
    by_style: dict[str, list[bool]] = {}
    for d in decisions:
        p = audience.personas[d.agent_index]
        by_style.setdefault(p.objection_style, []).append(d.stage1.action == "open")

    print(f"\nfunnel states: {dict(states)}")
    print(f"open rate: {opens}/{len(decisions)}")
    for style, flags in sorted(by_style.items()):
        print(f"  {style:>14}: {sum(flags)}/{len(flags)} opened")

    paths = {
        (d.stage1.action, d.reaction.action if d.reaction else "-") for d in decisions
    }
    print("\n--- GO/NO-GO ---")
    print(
        f"[{'PASS' if len(paths) >= 3 else 'FAIL'}] "
        f"reaction diversity: {len(paths)} distinct decision paths "
        f"({sorted(paths)})"
    )
    homogeneous = opens in (0, len(decisions))
    print(
        f"[{'PASS' if not homogeneous else 'FAIL'}] "
        "population not homogeneous at the attention gate"
    )
    if cfg.mode == "live":
        rate = engine.llm_calls / max(0.1, elapsed)
        print(
            f"[INFO] throughput: {rate:.2f} cognition calls/s "
            f"-> a 500-persona full-fidelity run ≈ {500 * 1.3 / max(rate, 0.01) / 60:.0f} min"
        )


if __name__ == "__main__":
    asyncio.run(main())
