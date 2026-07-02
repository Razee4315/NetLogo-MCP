"""Tests for stimulus ingestion, the event store, and calibration."""

from __future__ import annotations

import numpy as np
import pytest

from netlogo_mcp.market.calibration import (
    Calibration,
    fit_from_csv,
    load_base_rates,
)
from netlogo_mcp.market.schemas import (
    CampaignSpec,
    Decision,
    Reaction,
    Stage1Decision,
)
from netlogo_mcp.market.stimulus import (
    email_stimulus,
    list_campaigns,
    load_campaign_spec,
    load_saved_campaign,
    save_campaign_spec,
    social_ad_stimulus,
    stimulus_from_html,
)
from netlogo_mcp.market.store import EventStore, store_summary

# ── Stimulus ─────────────────────────────────────────────────────────────────


def test_email_builder_teaser_separation():
    s = email_stimulus(
        id="a",
        subject="Hello",
        sender="Acme <x@acme.io>",
        preheader="peek",
        body_text="Full body copy here.",
        cta="Buy now",
        price_shown="$10",
    )
    assert set(s.teaser) == {"subject", "sender", "preheader"}
    assert "Full body" not in s.teaser_text()
    assert s.channel_params.channel == "email"


def test_social_ad_builder():
    s = social_ad_stimulus(
        id="ad1",
        headline="Meals in 25 minutes",
        thumbnail_description="steaming bowl of pasta on a wooden table",
        body_text="FreshPlate delivers pre-portioned kits.",
        cta="Learn more",
    )
    assert s.type == "social_ad"
    assert s.visual_description
    assert s.channel_params.channel == "paid_social"


def test_stimulus_from_html_extracts_copy_cta_price():
    html = """
    <html><head><title>FreshPlate</title><style>.x{color:red}</style></head>
    <body>
      <h1>Dinner, solved</h1>
      <p>Three chef-designed meals delivered weekly. First box only $9.00,
      then $27.00/week. Skip any week.</p>
      <a class="btn primary" href="/go">Claim your $9 box</a>
      <script>track()</script>
    </body></html>
    """
    s = stimulus_from_html("v1", html, type="email", subject="Dinner, solved")
    assert "chef-designed" in s.body_text
    assert "track()" not in s.body_text
    assert s.cta == "Claim your $9 box"
    assert s.price_shown is not None and "9" in s.price_shown
    assert s.teaser["subject"] == "Dinner, solved"


def test_campaign_yaml_roundtrip(email_stimulus):
    spec = CampaignSpec(
        name="yaml-camp", audience="aud", stimuli=[email_stimulus], replicates=2
    )
    save_campaign_spec(spec)
    loaded = load_saved_campaign("yaml-camp")
    assert loaded.stimuli[0].id == email_stimulus.id
    assert any(c["name"] == "yaml-camp" for c in list_campaigns())


def test_load_campaign_spec_from_yaml_text():
    spec = load_campaign_spec(
        """
name: text-camp
audience: my-aud
replicates: 2
stimuli:
  - id: A
    type: email
    teaser: {subject: "Try us", sender: "Us"}
    body_text: "Body A"
    cta: "Go"
  - id: B
    variant_of: A
    type: email
    teaser: {subject: "Try us free today"}
    body_text: "Body B"
    cta: "Go"
"""
    )
    assert [s.id for s in spec.stimuli] == ["A", "B"]
    assert spec.stimuli[1].variant_of == "A"


def test_campaign_rejects_duplicate_stimulus_ids(email_stimulus):
    with pytest.raises(ValueError):
        CampaignSpec(
            name="dup", audience="a", stimuli=[email_stimulus, email_stimulus]
        )


# ── Event store ──────────────────────────────────────────────────────────────


def _decision(agent=0, tick=1, state="clicked", action="click", reason="ok"):
    return Decision(
        agent_index=agent,
        persona_id=f"p-{agent}",
        stimulus_id="v1",
        tick=tick,
        exposure_type="direct",
        stage1=Stage1Decision(action="open", reason="curious"),
        reaction=Reaction(
            attention_seconds=12,
            action=action,
            sentiment=0.4,
            reason=reason,
            objections=["price unclear"],
        ),
        state=state,
    )


def test_event_store_roundtrip():
    store = EventStore("unit-camp")
    run_id = store.create_run("aud", "v1", 0, 42, "python", "full")
    store.add_decisions(run_id, [_decision(i) for i in range(5)])
    store.add_tick_metrics(run_id, 1, {"unaware": 10, "clicked": 5}, wom_exposures=2)
    store.finish_run(run_id, ticks=24, llm_calls=10, cache_hits=3)

    runs = store.runs_df()
    assert len(runs) == 1 and runs.iloc[0]["status"] == "done"
    dec = store.decisions_df([run_id])
    assert len(dec) == 5
    assert dec.iloc[0]["reason"] == "ok"
    tm = store.tick_metrics_df([run_id])
    assert tm.iloc[0]["wom_exposures"] == 2
    assert store.completed_run_ids() == {"v1": [run_id]}
    summary = store_summary(store)
    assert summary["runs"] == 1 and summary["total_llm_calls"] == 10
    store.close()


def test_event_store_export(tmp_path):
    store = EventStore("exp-camp")
    run_id = store.create_run("aud", "v1", 0, 1, "python", "fast")
    store.add_decisions(run_id, [_decision()])
    files = store.export(str(tmp_path / "out"))
    assert len(files) == 3
    store.close()


# ── Calibration ──────────────────────────────────────────────────────────────


def test_base_rates_load():
    rates = load_base_rates()
    assert "email" in rates and "gate" in rates["email"]
    assert 0 < rates["email"]["gate"] < 1


def test_identity_calibration_passthrough():
    cal = Calibration()
    assert cal.is_identity()
    assert cal.apply("email", "gate", 0.42) == pytest.approx(0.42)


def test_single_pair_fit_hits_target():
    cal = Calibration()
    cal.fit_stage("email", "gate", [(0.60, 0.28)])
    # The observed simulated rate must map exactly onto the real rate.
    assert cal.apply("email", "gate", 0.60) == pytest.approx(0.28, abs=1e-6)
    # Monotone: better sim rate -> better calibrated rate.
    assert cal.apply("email", "gate", 0.70) > cal.apply("email", "gate", 0.50)


def test_fit_to_base_rates_and_persistence():
    cal = Calibration()
    cal.fit_to_base_rates("email", {"gate": 0.55, "click": 0.4, "convert": 0.3})
    base = load_base_rates()["email"]
    assert cal.apply("email", "gate", 0.55) == pytest.approx(base["gate"], abs=1e-6)
    path = cal.save()
    loaded = Calibration.load(path)
    assert loaded.apply("email", "click", 0.4) == pytest.approx(
        base["click"], abs=1e-6
    )


def test_multi_pair_fit_slope():
    cal = Calibration()
    pairs = [(0.6, 0.3), (0.4, 0.15), (0.8, 0.5)]
    cal.fit_stage("email", "gate", pairs)
    for sim, real in pairs:
        assert cal.apply("email", "gate", sim) == pytest.approx(real, abs=0.08)


def test_fit_from_csv(tmp_path):
    csv = tmp_path / "past.csv"
    csv.write_text(
        "sent,opened,clicked,converted\n10000,2800,300,25\n", encoding="utf-8"
    )
    cal = fit_from_csv(
        str(csv), "email", {"gate": 0.5, "click": 0.3, "convert": 0.2}
    )
    assert cal.apply("email", "gate", 0.5) == pytest.approx(0.28, abs=1e-3)
    assert cal.apply("email", "click", 0.3) == pytest.approx(300 / 2800, abs=1e-3)


def test_calibrated_funnel_dict():
    cal = Calibration()
    cal.fit_stage("email", "gate", [(0.5, 0.25)])
    out = cal.apply_funnel("email", {"gate": 0.5, "click": 0.2})
    assert out["gate"] == pytest.approx(0.25, abs=1e-6)
    assert out["click"] == pytest.approx(0.2)  # no map fitted -> passthrough


def test_extreme_rates_clamped():
    cal = Calibration()
    cal.fit_stage("email", "gate", [(0.5, 0.25)])
    assert 0.0 < cal.apply("email", "gate", 0.0001) < 0.01
    assert 0.5 < cal.apply("email", "gate", 0.9999) <= 1.0
    assert np.isfinite(cal.apply("email", "gate", 1.0))
