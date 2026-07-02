"""Analytics + report tests on a real (heuristic) campaign run."""

from __future__ import annotations

from pathlib import Path

import pytest

from netlogo_mcp.market import analytics
from netlogo_mcp.market.archetypes import assign_archetypes
from netlogo_mcp.market.cognition import HeuristicBackend
from netlogo_mcp.market.orchestrator import run_campaign
from netlogo_mcp.market.personas import generate_audience
from netlogo_mcp.market.report import (
    build_report_data,
    generate_report,
    render_html,
    render_markdown,
)
from netlogo_mcp.market.schemas import AudienceSpec, CampaignSpec
from netlogo_mcp.market.store import EventStore


@pytest.fixture(scope="function")
def ran_campaign(email_stimulus, tmp_path, monkeypatch):
    """One A/B campaign fully run on PythonWorld + heuristics."""
    monkeypatch.setenv("SYNTH_DATA_DIR", str(tmp_path / "md"))
    spec = AudienceSpec(
        name="rep-aud", size=100, seed=17, product_context="a meal-kit service"
    )
    audience = assign_archetypes(generate_audience(spec))
    variant_b = email_stimulus.model_copy(
        update={
            "id": "v2",
            "variant_of": "v1",
            "teaser": {"subject": "FREE FREE FREE!!! ACT NOW!!!", "sender": "x"},
            "body_text": "100% guarantee, limited time, don't miss out!!!",
        }
    )
    campaign = CampaignSpec(
        name="rep-camp",
        audience=spec.name,
        stimuli=[email_stimulus, variant_b],
        replicates=3,
        fidelity="full",
        max_ticks=48,
        seed=3,
    )
    store = EventStore(campaign.name)
    import asyncio

    asyncio.get_event_loop_policy()
    summary = asyncio.run(
        run_campaign(campaign, audience, store=store, backend=HeuristicBackend())
    )
    yield campaign, audience, store, summary
    store.close()


def test_funnel_summary_shapes(ran_campaign):
    campaign, audience, store, _ = ran_campaign
    funnel = analytics.funnel_summary(store, audience)
    assert set(funnel) == {"v1", "v2"}
    for v in funnel.values():
        assert v["replicates"] == 3
        m = v["metrics"]
        assert m["reach"]["mean"] == pytest.approx(1.0)
        assert 0 <= m["gate"]["lo"] <= m["gate"]["mean"] <= m["gate"]["hi"] <= 1
        assert set(v["raw"]) == {"gate", "click", "convert"}


def test_segment_breakdown_covers_population(ran_campaign):
    campaign, audience, store, _ = ran_campaign
    segments = analytics.segment_breakdown(store, audience, "v1")
    styles = [s for s in segments if s["dimension"] == "objection_style"]
    assert sum(s["n"] for s in styles) == audience.size * 3  # 3 replicates
    for s in styles:
        assert 0 <= s["conversion_rate"] <= s["click_rate"] <= s["engaged_rate"] <= 1


def test_objection_mining_returns_themes(ran_campaign):
    campaign, audience, store, _ = ran_campaign
    themes = analytics.mine_objections(store, "v1")
    assert themes
    top = themes[0]
    assert top["count"] >= 1 and top["quotes"] and top["theme"]


def test_variant_comparison_prefers_clean_copy(ran_campaign):
    campaign, audience, store, _ = ran_campaign
    comparisons = analytics.compare_variants(store, audience)
    engagement = next(c for c in comparisons if c["metric"] == "engagement")
    assert engagement["winner"] == "v1"  # spam variant must lose engagement
    assert 0 <= engagement["p_value"] <= 1


def test_wom_stats(ran_campaign):
    campaign, audience, store, _ = ran_campaign
    wom = analytics.wom_stats(store, "v1")
    assert wom["direct_exposures"] >= audience.size
    assert wom["amplification"] >= 0


def test_report_markdown_content(ran_campaign):
    campaign, audience, store, _ = ran_campaign
    data = build_report_data(campaign, audience, store)
    assert data["heuristic_mode"] is True
    md = render_markdown(data)
    assert "# Pre-Flight Report — rep-camp" in md
    assert "Variant `v1`" in md and "Variant `v2`" in md
    assert "A/B verdict" in md
    assert "Heuristic cognition" in md  # honest-mode disclaimer
    assert "attention gate" in md
    assert "rehearsal, not the market" in md


def test_report_html_renders_with_charts(ran_campaign):
    campaign, audience, store, _ = ran_campaign
    data = build_report_data(campaign, audience, store)
    html = render_html(data)
    assert "<!DOCTYPE html>" in html
    assert "plotly" in html.lower()
    assert "Funnel by variant" in html
    assert "<script" in html  # chart payload made it in


def test_generate_report_writes_files(ran_campaign):
    campaign, audience, store, _ = ran_campaign
    result = generate_report(campaign, audience, store)
    assert Path(result["markdown_path"]).is_file()
    assert Path(result["html_path"]).is_file()
    assert result["markdown"].startswith("# Pre-Flight Report")
