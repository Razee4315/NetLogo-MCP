"""End-to-end campaign runs on PythonWorld + HeuristicBackend."""

from __future__ import annotations

import pytest

from netlogo_mcp.market.archetypes import assign_archetypes
from netlogo_mcp.market.cognition import HeuristicBackend
from netlogo_mcp.market.orchestrator import run_campaign
from netlogo_mcp.market.personas import generate_audience, save_audience
from netlogo_mcp.market.schemas import AudienceSpec, CampaignSpec
from netlogo_mcp.market.store import EventStore


@pytest.fixture
def audience():
    spec = AudienceSpec(
        name="e2e-aud", size=80, seed=13, product_context="a meal-kit service"
    )
    aud = assign_archetypes(generate_audience(spec))
    save_audience(aud)
    return aud


async def test_full_campaign_run(audience, campaign):
    campaign = campaign.model_copy(
        update={"audience": audience.spec.name, "replicates": 2}
    )
    store = EventStore(campaign.name)
    summary = await run_campaign(
        campaign, audience, store=store, backend=HeuristicBackend()
    )
    assert len(summary["runs"]) == 2  # 1 variant x 2 replicates
    for run in summary["runs"]:
        counts = run["final_counts"]
        assert sum(counts.values()) == audience.size
        assert counts["unaware"] == 0  # reach=1.0 email touches everyone
        assert run["ticks"] >= 1

    # Store agrees with the summary.
    runs_df = store.runs_df()
    assert (runs_df["status"] == "done").all()
    decisions = store.decisions_df()
    assert len(decisions) >= audience.size * 2  # every exposure resolved, per rep
    assert set(decisions["state"]) <= {
        "engaged", "clicked", "converted", "ignored", "annoyed",
    }
    tm = store.tick_metrics_df()
    assert not tm.empty
    store.close()


async def test_paired_variants_share_seed_and_reach(audience, email_stimulus):
    variant_b = email_stimulus.model_copy(
        update={
            "id": "v2",
            "variant_of": "v1",
            "teaser": {"subject": "URGENT!!! FREE MEALS ACT NOW!!!", "sender": "x"},
            "body_text": "FREE FREE FREE limited time 100% guarantee!!!",
        }
    )
    campaign = CampaignSpec(
        name="ab-camp",
        audience=audience.spec.name,
        stimuli=[email_stimulus, variant_b],
        replicates=1,
        fidelity="full",
        seed=21,
    )
    store = EventStore(campaign.name)
    summary = await run_campaign(
        campaign, audience, store=store, backend=HeuristicBackend()
    )
    by_variant = {r["stimulus_id"]: r for r in summary["runs"]}
    assert by_variant["v1"]["seed"] == by_variant["v2"]["seed"]  # paired

    # The spammy variant must not beat the clean variant on engagement.
    def engaged_plus(counts):
        return counts["engaged"] + counts["clicked"] + counts["converted"]

    assert engaged_plus(by_variant["v2"]["final_counts"]) <= engaged_plus(
        by_variant["v1"]["final_counts"]
    )
    store.close()


async def test_word_of_mouth_occurs_in_engaged_population(audience, email_stimulus):
    """With a heuristic population this size, at least some sharing should
    cascade into social exposures."""
    campaign = CampaignSpec(
        name="wom-camp",
        audience=audience.spec.name,
        stimuli=[email_stimulus],
        replicates=3,
        fidelity="full",
        max_ticks=48,
        seed=5,
    )
    store = EventStore(campaign.name)
    await run_campaign(campaign, audience, store=store, backend=HeuristicBackend())
    decisions = store.decisions_df()
    assert (decisions["exposure_type"] == "social").sum() > 0
    store.close()


async def test_fast_fidelity_uses_fewer_calls_than_full(audience, campaign):
    campaign_full = campaign.model_copy(
        update={"audience": audience.spec.name, "name": "fid-full", "fidelity": "full"}
    )
    campaign_fast = campaign_full.model_copy(
        update={"name": "fid-fast", "fidelity": "fast"}
    )
    s_full = await run_campaign(
        campaign_full, audience,
        store=EventStore("fid-full"), backend=HeuristicBackend(),
    )
    s_fast = await run_campaign(
        campaign_fast, audience,
        store=EventStore("fid-fast"), backend=HeuristicBackend(),
    )
    assert s_fast["total_llm_calls"] < s_full["total_llm_calls"]


async def test_progress_callback_invoked(audience, campaign):
    campaign = campaign.model_copy(update={"audience": audience.spec.name})
    messages: list[str] = []
    await run_campaign(
        campaign,
        audience,
        store=EventStore(campaign.name),
        backend=HeuristicBackend(),
        on_progress=messages.append,
    )
    assert any("replicate" in m for m in messages)
    assert any("done" in m for m in messages)
