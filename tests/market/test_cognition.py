"""Cognition engine tests — heuristic backend, caching, fidelity modes, and
the LLM transport exercised against a fake OpenAI-compatible server."""

from __future__ import annotations

import json

import httpx
import pytest

from netlogo_mcp.market.archetypes import assign_archetypes
from netlogo_mcp.market.cognition import (
    CognitionEngine,
    HeuristicBackend,
    LLMBackend,
    OpenAICompatClient,
    ResponseCache,
    _extract_json,
)
from netlogo_mcp.market.config import LLMConfig
from netlogo_mcp.market.personas import generate_audience
from netlogo_mcp.market.schemas import (
    AudienceSpec,
    ExposureEvent,
    Persona,
    Stage1Decision,
)


def _event(agent=0, count=1, etype="direct", tick=1) -> ExposureEvent:
    return ExposureEvent(
        agent_index=agent, exposure_type=etype, exposure_count=count, tick=tick
    )


def _persona(**overrides) -> Persona:
    base = dict(
        id="x",
        age=35,
        occupation="teacher",
        persona_card="I'm a 35-year-old teacher who cooks most nights.",
        category_involvement=0.5,
        trust_in_ads=0.3,
    )
    base.update(overrides)
    return Persona(**base)


# ── Heuristic backend ────────────────────────────────────────────────────────


async def test_heuristic_is_deterministic(email_stimulus):
    b = HeuristicBackend()
    p = _persona()
    d1 = await b.stage1(p, email_stimulus, _event(), None, seed=1)
    d2 = await b.stage1(p, email_stimulus, _event(), None, seed=1)
    assert d1 == d2


async def test_heuristic_personas_differentiate(email_stimulus):
    """Engaged low-skepticism personas must open far more than disengaged
    skeptics — the core 'reactions differ by persona' property."""
    b = HeuristicBackend()
    enthusiast = _persona(
        id="e",
        category_involvement=0.95,
        trust_in_ads=0.8,
        novelty_seeking=0.9,
        channels={"email": 0.95},
        pain_points=["not enough time"],
        objection_style="enthusiast",
    )
    skeptic = _persona(
        id="s",
        category_involvement=0.05,
        trust_in_ads=0.05,
        novelty_seeking=0.1,
        channels={"email": 0.05},
        objection_style="skeptic",
    )
    opens = {"e": 0, "s": 0}
    for seed in range(60):
        for p in (enthusiast, skeptic):
            d = await b.stage1(p, email_stimulus, _event(), None, seed=seed)
            opens[p.id] += d.action == "open"
    assert opens["e"] > opens["s"] * 2
    assert opens["s"] < 20  # skeptics mostly ignore


async def test_fatigue_reduces_opens(email_stimulus):
    b = HeuristicBackend()
    p = _persona(category_involvement=0.6, channels={"email": 0.6})
    first = third = 0
    for s in range(80):
        d1 = await b.stage1(p, email_stimulus, _event(count=1), None, s)
        d3 = await b.stage1(p, email_stimulus, _event(count=3), None, s)
        first += d1.action == "open"
        third += d3.action == "open"
    assert third < first


async def test_stage2_produces_valid_reaction(email_stimulus):
    b = HeuristicBackend()
    for seed in range(30):
        r = await b.stage2(_persona(), email_stimulus, _event(), seed)
        assert -1 <= r.sentiment <= 1
        assert r.action in (
            "ignore",
            "click",
            "save_for_later",
            "buy",
            "share",
            "unsubscribe",
            "report_spam",
        )
        assert r.reason


async def test_stage2_price_sensitive_objects_to_hidden_price(email_stimulus):
    b = HeuristicBackend()
    no_price = email_stimulus.model_copy(update={"price_shown": None})
    p = _persona(price_sensitivity=0.9)
    r = await b.stage2(p, no_price, _event(), 1)
    assert any("price" in o for o in r.objections)


# ── Response cache ───────────────────────────────────────────────────────────


def test_response_cache_roundtrip(tmp_path):
    c = ResponseCache(str(tmp_path / "c.sqlite"))
    assert c.get("nope") is None
    c.put("k", {"a": [1, 2]})
    assert c.get("k") == {"a": [1, 2]}
    c.put("k", {"a": 3})
    assert c.get("k") == {"a": 3}
    c.close()


# ── Engine: fidelity + caching ───────────────────────────────────────────────


@pytest.fixture
def audience():
    spec = AudienceSpec(name="cog-aud", size=60, seed=5, product_context="meal kits")
    return assign_archetypes(generate_audience(spec))


async def test_full_fidelity_every_agent_individual(audience, email_stimulus):
    eng = CognitionEngine(audience, backend=HeuristicBackend(), fidelity="full")
    events = [_event(agent=i) for i in range(20)]
    decisions = await eng.decide_batch(events, email_stimulus)
    assert len(decisions) == 20
    assert all(d.persona_id == audience.personas[d.agent_index].id for d in decisions)


async def test_fast_fidelity_amortizes_backend_calls(audience, email_stimulus):
    backend = HeuristicBackend()
    eng = CognitionEngine(audience, backend=backend, fidelity="fast", archetype_draws=3)
    events = [_event(agent=i) for i in range(60)]
    await eng.decide_batch(events, email_stimulus)
    n_arch = len({p.archetype for p in audience.personas})
    # Stage-1 calls bounded by archetypes x draws, not by 60 agents.
    assert backend.calls <= n_arch * 3 * 2  # x2 for possible stage-2 calls
    assert backend.calls < 60


async def test_exact_cache_hits_on_rerun(audience, email_stimulus):
    cache_path = None
    eng1 = CognitionEngine(audience, backend=HeuristicBackend(), fidelity="full")
    cache_path = eng1.cache.path
    events = [_event(agent=i) for i in range(10)]
    await eng1.decide_batch(events, email_stimulus)

    backend2 = HeuristicBackend()
    eng2 = CognitionEngine(
        audience,
        backend=backend2,
        fidelity="full",
        cache=ResponseCache(cache_path),
    )
    d2 = await eng2.decide_batch(events, email_stimulus)
    assert backend2.calls == 0  # everything served from cache
    assert all(d.cached for d in d2)


async def test_decisions_map_to_funnel_states(audience, email_stimulus):
    eng = CognitionEngine(audience, backend=HeuristicBackend(), fidelity="full")
    decisions = await eng.decide_batch(
        [_event(agent=i) for i in range(40)], email_stimulus
    )
    valid = {"engaged", "clicked", "converted", "ignored", "annoyed"}
    assert {d.state for d in decisions} <= valid
    # Population-level sanity: not everyone converts, not everyone ignores.
    states = [d.state for d in decisions]
    assert states.count("converted") < 20
    assert len(set(states)) >= 2


async def test_interview_returns_text(audience):
    eng = CognitionEngine(audience, backend=HeuristicBackend())
    answer = await eng.interview(0, "What would make you trust this brand?")
    assert isinstance(answer, str) and len(answer) > 40


# ── JSON extraction ──────────────────────────────────────────────────────────


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert _extract_json('Sure!\n```json\n{"a": 1}\n```\nDone.') == {"a": 1}


def test_extract_json_with_chatter():
    assert _extract_json('Here you go: {"a": {"b": 2}} hope that helps') == {
        "a": {"b": 2}
    }


# ── LLM transport against a fake OpenAI-compatible server ────────────────────


def _fake_server(behavior: str):
    """Returns an httpx MockTransport emulating an OpenAI-compatible API."""
    calls = {"n": 0, "formats": []}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(request.content)
        calls["formats"].append((body.get("response_format") or {}).get("type"))
        if behavior == "no_json_schema" and (
            (body.get("response_format") or {}).get("type") == "json_schema"
        ):
            return httpx.Response(400, json={"error": "response_format unsupported"})
        content = json.dumps({"reason": "meh, not for me", "action": "scroll_past"})
        if behavior == "fenced":
            content = f"```json\n{content}\n```"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    return httpx.MockTransport(handler), calls


def _client_with(transport) -> OpenAICompatClient:
    cfg = LLMConfig(mode="live", base_url="http://fake/v1", model="test-model")
    client = OpenAICompatClient(cfg)
    client._client = httpx.AsyncClient(
        transport=transport, base_url=cfg.base_url, timeout=5
    )
    return client


async def test_llm_backend_stage1_happy_path(email_stimulus):
    transport, calls = _fake_server("ok")
    backend = LLMBackend(LLMConfig(mode="live"))
    backend.client = _client_with(transport)
    d = await backend.stage1(_persona(), email_stimulus, _event(), None, seed=1)
    assert isinstance(d, Stage1Decision)
    assert d.action == "scroll_past"
    assert calls["n"] == 1


async def test_llm_client_degrades_when_json_schema_unsupported(email_stimulus):
    transport, calls = _fake_server("no_json_schema")
    backend = LLMBackend(LLMConfig(mode="live"))
    backend.client = _client_with(transport)
    d = await backend.stage1(_persona(), email_stimulus, _event(), None, seed=1)
    assert d.action == "scroll_past"
    # First attempt json_schema (400), then json_object succeeds; the working
    # mode is remembered for subsequent calls.
    assert calls["formats"][0] == "json_schema"
    assert calls["formats"][1] == "json_object"
    await backend.stage1(_persona(), email_stimulus, _event(), None, seed=2)
    assert calls["formats"][2] == "json_object"


async def test_llm_backend_parses_fenced_output(email_stimulus):
    transport, _ = _fake_server("fenced")
    backend = LLMBackend(LLMConfig(mode="live"))
    backend.client = _client_with(transport)
    d = await backend.stage1(_persona(), email_stimulus, _event(), None, seed=1)
    assert d.action == "scroll_past"
    assert "meh" in d.reason
