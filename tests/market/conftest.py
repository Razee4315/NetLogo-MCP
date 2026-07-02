"""Shared fixtures for market-module tests. No JVM, no network, no LLM."""

from __future__ import annotations

import pytest

from netlogo_mcp.market.schemas import (
    AudienceSpec,
    CampaignSpec,
    ChannelParams,
    NetworkSpec,
    Stimulus,
)


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Every test gets its own market_data root."""
    monkeypatch.setenv("SYNTH_DATA_DIR", str(tmp_path / "market_data"))
    monkeypatch.setenv("SYNTH_LLM_MODE", "mock")
    yield


@pytest.fixture
def small_spec() -> AudienceSpec:
    return AudienceSpec(
        name="test-audience",
        product_context="a meal-kit subscription service",
        size=40,
        seed=7,
        network=NetworkSpec(topology="watts-strogatz", k=4, rewire=0.1),
    )


@pytest.fixture
def email_stimulus() -> Stimulus:
    return Stimulus(
        id="v1",
        type="email",
        teaser={
            "subject": "Dinner, solved: 3 chef-designed meals for $9",
            "sender": "FreshPlate <hello@freshplate.example>",
            "preheader": "No planning, no waste — first box discounted",
        },
        body_text=(
            "Weeknights are chaos. FreshPlate delivers 3 chef-designed meal "
            "kits with pre-portioned ingredients. Cook in 25 minutes. Skip "
            "or cancel any week. First box $9 instead of $27."
        ),
        cta="Claim your $9 first box",
        offer="first box 66% off",
        price_shown="$9 first box, then $27/week",
        channel_params=ChannelParams(channel="email", send_tick=1, reach=1.0),
    )


@pytest.fixture
def campaign(email_stimulus) -> CampaignSpec:
    return CampaignSpec(
        name="test-campaign",
        audience="test-audience",
        stimuli=[email_stimulus],
        replicates=1,
        max_ticks=24,
        fidelity="full",
        seed=11,
    )
