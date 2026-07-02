"""MCP tool surface tests — full conversational flow, no JVM required."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp.exceptions import ToolError

from netlogo_mcp.market.tools import (
    calibrate,
    compare_campaign_variants,
    create_campaign,
    generate_audience,
    get_audience,
    get_campaign_report,
    interview_persona,
    list_audiences,
    list_campaigns,
    market_info,
    run_campaign,
)

AUDIENCE_YAML = """
name: tool-aud
product_context: "a meal-kit subscription"
size: 60
seed: 11
distributions:
  trust_in_ads: {mean: 0.35, sd: 0.15}
network: {topology: watts-strogatz, k: 4}
"""

CAMPAIGN_YAML = """
name: tool-camp
audience: tool-aud
replicates: 2
max_ticks: 36
fidelity: full
seed: 7
stimuli:
  - id: A
    type: email
    teaser:
      subject: "Dinner, solved: 3 chef-designed meals"
      sender: "FreshPlate"
    body_text: "Cook in 25 minutes. Skip or cancel any week. First box $9."
    cta: "Claim your $9 first box"
    price_shown: "$9 first box, then $27/week"
  - id: B
    variant_of: A
    type: email
    teaser:
      subject: "FREE MEALS!!! Don't miss out — ACT NOW"
      sender: "FreshPlate"
    body_text: "100% guarantee!!! Limited time! FREE FREE FREE."
    cta: "CLICK HERE"
"""


@pytest.fixture
def ctx():
    c = MagicMock()
    c.info = AsyncMock()
    return c


async def test_full_tool_flow(ctx):
    # 1. audience
    out = await generate_audience(AUDIENCE_YAML, ctx)
    assert "tool-aud" in out and "archetype" in out
    assert "tool-aud" in await list_audiences(ctx)
    detail = await get_audience("tool-aud", ctx, sample=2)
    assert "persona" in detail.lower() or "tool-aud" in detail

    # 2. campaign
    out = await create_campaign(CAMPAIGN_YAML, ctx)
    assert "tool-camp" in out
    assert "tool-camp" in await list_campaigns(ctx)

    # 3. run (python engine — no JVM)
    out = await run_campaign("tool-camp", ctx, engine="python")
    assert "complete" in out
    assert "| A |" in out and "| B |" in out
    assert "heuristic backend" in out  # honest mock-mode note

    # 4. report
    report = await get_campaign_report("tool-camp", ctx)
    assert "# Pre-Flight Report — tool-camp" in report
    assert "A/B verdict" in report
    assert "HTML report" in report

    # 5. compare
    comparison = await compare_campaign_variants("tool-camp", ctx)
    assert "winner" in comparison
    assert "**A**" in comparison or "**B**" in comparison

    # 6. focus group
    qa = await interview_persona("tool-aud", "Why would you ignore this?", ctx, n=2)
    assert "Q:" in qa and qa.count("**tool-aud-") == 2

    # 7. calibration (benchmark anchoring)
    out = await calibrate(ctx, channel="email", campaign_name="tool-camp")
    assert "calibrated" in out.lower()

    # 8. status
    info = await market_info(ctx)
    assert "tool-aud" in info and "tool-camp" in info and "email" in info


async def test_generate_audience_rejects_bad_yaml(ctx):
    with pytest.raises(ToolError):
        await generate_audience("size: [not-a-mapping", ctx)
    with pytest.raises(ToolError):
        await generate_audience("just a string", ctx)


async def test_create_campaign_requires_existing_audience(ctx):
    yaml_text = CAMPAIGN_YAML.replace("audience: tool-aud", "audience: ghost")
    with pytest.raises(ToolError):
        await create_campaign(yaml_text, ctx)


async def test_run_campaign_unknown_engine(ctx):
    await generate_audience(AUDIENCE_YAML, ctx)
    await create_campaign(CAMPAIGN_YAML, ctx)
    with pytest.raises(ToolError):
        await run_campaign("tool-camp", ctx, engine="quantum")


async def test_report_before_run_fails_cleanly(ctx):
    await generate_audience(AUDIENCE_YAML, ctx)
    await create_campaign(CAMPAIGN_YAML, ctx)
    with pytest.raises(ToolError):
        await get_campaign_report("tool-camp", ctx)


async def test_interview_unknown_persona(ctx):
    await generate_audience(AUDIENCE_YAML, ctx)
    with pytest.raises(ToolError):
        await interview_persona("tool-aud", "hi", ctx, persona_id="nope-0001")
