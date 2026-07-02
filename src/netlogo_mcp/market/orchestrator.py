"""Campaign orchestrator — the tick loop that joins world and cognition.

Per (stimulus variant x replicate):

    world.step()                      # NetLogo/Python advances social physics
    events = world.pending_exposures()  # ONE batched read
    decisions = engine.decide_batch(events)  # LLM/heuristic, concurrent
    world.apply_decisions(decisions)  # ONE batched write
    store.add_*(...)                  # event log + tick metrics

Paired A/B design: replicate r uses the same world seed for every variant,
so variants face the identical audience, reach sample, and network dice —
differences in outcomes are attributable to the creative alone.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .cognition import CognitionEngine, ResponseCache
from .schemas import Audience, CampaignSpec, Decision, ExposureEvent, Stimulus
from .store import EventStore
from .worlds import PythonWorld, WorldBridge

logger = logging.getLogger("netlogo_mcp.market.orchestrator")

ProgressFn = Callable[[str], Any] | None
WorldFactory = Callable[[], WorldBridge]


def _run_seed(campaign_seed: int, replicate: int) -> int:
    return campaign_seed + replicate * 7919  # prime stride, paired across variants


async def _maybe_call(fn: ProgressFn, message: str) -> None:
    if fn is None:
        return
    result = fn(message)
    if isinstance(result, Awaitable):
        await result


async def run_single(
    world: WorldBridge,
    engine: CognitionEngine,
    store: EventStore,
    campaign: CampaignSpec,
    audience: Audience,
    stimulus: Stimulus,
    replicate: int,
    engine_name: str,
    on_progress: ProgressFn = None,
    tick_delay_s: float = 0.0,
) -> dict[str, Any]:
    """One simulation run. Returns a summary dict."""
    seed = _run_seed(campaign.seed, replicate)
    run_id = store.create_run(
        audience=audience.spec.name,
        stimulus_id=stimulus.id,
        replicate=replicate,
        seed=seed,
        engine=engine_name,
        fidelity=campaign.fidelity,
    )
    calls_before = engine.llm_calls
    hits_before = engine.cache_hits
    started = time.time()
    verbatims: dict[int, str] = {}  # sharer agent_index -> verbatim reason
    tick = 0
    status = "done"

    try:
        await world.setup(audience, stimulus, seed)
        for _ in range(campaign.max_ticks):
            tick = await world.step()
            events = await world.pending_exposures()
            for ev in events:
                if ev.exposure_type == "social" and ev.source_index is not None:
                    ev.source_comment = verbatims.get(ev.source_index, "")
            decisions = await engine.decide_batch(events, stimulus)
            await world.apply_decisions(decisions)
            for d in decisions:
                if d.will_share:
                    verbatims[d.agent_index] = d.verbatim
            if decisions:
                store.add_decisions(run_id, decisions)
            counts = await world.state_counts()
            store.add_tick_metrics(
                run_id, tick, counts, wom_exposures=await world.wom_this_tick()
            )
            if tick_delay_s > 0:
                await asyncio.sleep(tick_delay_s)
            if await world.is_quiet():
                break
    except Exception:
        status = "failed"
        raise
    finally:
        store.finish_run(
            run_id,
            ticks=tick,
            llm_calls=engine.llm_calls - calls_before,
            cache_hits=engine.cache_hits - hits_before,
            status=status,
        )
        await world.teardown()

    counts = await world.state_counts()
    summary = {
        "run_id": run_id,
        "stimulus_id": stimulus.id,
        "replicate": replicate,
        "seed": seed,
        "ticks": tick,
        "duration_s": round(time.time() - started, 2),
        "llm_calls": engine.llm_calls - calls_before,
        "cache_hits": engine.cache_hits - hits_before,
        "final_counts": counts,
    }
    await _maybe_call(
        on_progress,
        f"[{stimulus.id} r{replicate}] done in {summary['duration_s']}s "
        f"({tick} ticks, {summary['llm_calls']} cognition calls): "
        f"{counts.get('converted', 0)} converted, "
        f"{counts.get('clicked', 0)} clicked",
    )
    return summary


async def run_campaign(
    campaign: CampaignSpec,
    audience: Audience,
    world_factory: WorldFactory | None = None,
    store: EventStore | None = None,
    backend: Any = None,
    on_progress: ProgressFn = None,
    tick_delay_s: float = 0.0,
) -> dict[str, Any]:
    """Run every stimulus variant x replicate. Returns the campaign summary.

    ``world_factory`` defaults to ``PythonWorld`` (no NetLogo needed);
    ``market/tools.py`` passes a NetLogo-backed factory. One response cache
    is shared across all runs, so identical exposures are never re-computed.
    """
    if world_factory is None:
        world_factory = PythonWorld
    own_store = store is None
    store = store or EventStore(campaign.name)
    cache = ResponseCache()
    engine_name = "python" if world_factory is PythonWorld else "netlogo"

    runs: list[dict[str, Any]] = []
    try:
        for stimulus in campaign.stimuli:
            for replicate in range(campaign.replicates):
                engine = CognitionEngine(
                    audience,
                    backend=backend,
                    fidelity=campaign.fidelity,
                    full_fidelity_sample=campaign.full_fidelity_sample,
                    seed=_run_seed(campaign.seed, replicate),
                    cache=cache,
                )
                await _maybe_call(
                    on_progress,
                    f"running variant '{stimulus.id}' replicate "
                    f"{replicate + 1}/{campaign.replicates} ...",
                )
                runs.append(
                    await run_single(
                        world_factory(),
                        engine,
                        store,
                        campaign,
                        audience,
                        stimulus,
                        replicate,
                        engine_name,
                        on_progress,
                        tick_delay_s,
                    )
                )
    finally:
        if own_store:
            store.close()

    return {
        "campaign": campaign.name,
        "audience": audience.spec.name,
        "variants": [s.id for s in campaign.stimuli],
        "replicates": campaign.replicates,
        "fidelity": campaign.fidelity,
        "total_llm_calls": sum(r["llm_calls"] for r in runs),
        "runs": runs,
    }


__all__ = [
    "run_campaign",
    "run_single",
    "PythonWorld",
    "WorldBridge",
    "Decision",
    "ExposureEvent",
]
