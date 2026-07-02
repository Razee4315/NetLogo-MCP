"""World-rule tests against PythonWorld (the reference implementation), plus
NetLogoWorld's batching contract against fake command/report callables."""

from __future__ import annotations

import numpy as np

from netlogo_mcp.market.netlogo_gen import market_model_code, market_model_widgets
from netlogo_mcp.market.personas import generate_audience
from netlogo_mcp.market.schemas import (
    AudienceSpec,
    ChannelParams,
    Decision,
    NetworkSpec,
    Reaction,
    Stage1Decision,
)
from netlogo_mcp.market.worlds import NetLogoWorld, PythonWorld


def _audience(n=30, seed=3, k=4):
    return generate_audience(
        AudienceSpec(
            name="world-aud",
            size=n,
            seed=seed,
            network=NetworkSpec(topology="watts-strogatz", k=k),
        )
    )


def _decision(i, state="clicked", sentiment=0.5, will_share=False, tick=1):
    return Decision(
        agent_index=i,
        persona_id=f"p{i}",
        stimulus_id="v1",
        tick=tick,
        exposure_type="direct",
        stage1=Stage1Decision(action="open", reason="r"),
        reaction=Reaction(
            attention_seconds=10, action="click", sentiment=sentiment, reason="r"
        ),
        state=state,
        will_share=will_share,
    )


# ── PythonWorld rules ────────────────────────────────────────────────────────


async def test_email_delivers_once_at_send_tick(email_stimulus):
    world = PythonWorld()
    aud = _audience()
    await world.setup(aud, email_stimulus, seed=1)

    await world.step()  # tick 1 == send_tick
    events = await world.pending_exposures()
    assert len(events) == aud.size  # reach=1.0
    assert all(e.exposure_type == "direct" for e in events)

    # Nobody re-delivered while pending.
    await world.step()
    assert len(await world.pending_exposures()) == aud.size


async def test_reach_fraction_respected(email_stimulus):
    world = PythonWorld()
    aud = _audience(n=200)
    stim = email_stimulus.model_copy(
        update={"channel_params": ChannelParams(channel="email", reach=0.5)}
    )
    await world.setup(aud, stim, seed=2)
    await world.step()
    events = await world.pending_exposures()
    assert 70 <= len(events) <= 130  # ~50% of 200


async def test_unaware_becomes_exposed_on_delivery(email_stimulus):
    world = PythonWorld()
    await world.setup(_audience(), email_stimulus, seed=1)
    await world.step()
    counts = await world.state_counts()
    assert counts["unaware"] == 0
    assert counts["exposed"] == 30


async def test_decisions_update_state_and_clear_pending(email_stimulus):
    world = PythonWorld()
    aud = _audience()
    await world.setup(aud, email_stimulus, seed=1)
    await world.step()
    events = await world.pending_exposures()
    decisions = [_decision(e.agent_index, state="ignored") for e in events]
    await world.apply_decisions(decisions)
    assert await world.pending_exposures() == []
    counts = await world.state_counts()
    assert counts["ignored"] == aud.size


async def test_share_schedules_neighbors_with_delay(email_stimulus):
    world = PythonWorld()
    aud = _audience()
    await world.setup(aud, email_stimulus, seed=1)
    await world.step()
    events = await world.pending_exposures()
    # Everyone ignores except agent 0 who shares.
    decisions = [
        _decision(e.agent_index, state="ignored") for e in events if e.agent_index != 0
    ]
    decisions.append(_decision(0, state="clicked", will_share=True))
    await world.apply_decisions(decisions)

    # Within WOM delay window, neighbors of 0 receive social exposures.
    social_events = []
    for _ in range(7):
        await world.step()
        for e in await world.pending_exposures():
            if e.exposure_type == "social":
                social_events.append(e)
                await world.apply_decisions([_decision(e.agent_index, "ignored")])
    assert social_events, "sharing must produce social exposures"
    assert {e.source_index for e in social_events} == {0}
    assert {e.agent_index for e in social_events} <= set(aud.edges[0])


async def test_frequency_cap_limits_paid_social(email_stimulus):
    world = PythonWorld()
    aud = _audience(n=40)
    stim = email_stimulus.model_copy(
        update={
            "type": "social_ad",
            "channel_params": ChannelParams(
                channel="paid_social",
                reach=1.0,
                impressions_per_tick=1.0,
                frequency_cap=2,
            ),
        }
    )
    await world.setup(aud, stim, seed=4)
    total_exposures = 0
    for _ in range(20):
        await world.step()
        events = await world.pending_exposures()
        total_exposures += len(events)
        await world.apply_decisions(
            [_decision(e.agent_index, state="ignored") for e in events]
        )
        if await world.is_quiet():
            break
    assert total_exposures <= 40 * 2  # cap respected
    assert await world.is_quiet()
    assert max(world.exposure_count) <= 2


async def test_sentiment_drift_toward_neighbors(email_stimulus):
    world = PythonWorld()
    aud = _audience()
    await world.setup(aud, email_stimulus, seed=1)
    await world.step()
    events = await world.pending_exposures()
    decisions = [_decision(e.agent_index, "clicked", sentiment=0.9) for e in events]
    decisions[0] = _decision(0, "ignored", sentiment=-0.9)
    await world.apply_decisions(decisions)
    before = world.sentiment[0]
    for _ in range(10):
        await world.step()
    assert world.sentiment[0] > before  # pulled up toward positive neighbors


async def test_quiet_after_email_settles(email_stimulus):
    world = PythonWorld()
    await world.setup(_audience(), email_stimulus, seed=1)
    await world.step()
    events = await world.pending_exposures()
    await world.apply_decisions(
        [_decision(e.agent_index, state="ignored") for e in events]
    )
    await world.step()
    assert await world.is_quiet()


async def test_paired_seed_reproduces_reach(email_stimulus):
    aud = _audience(n=100)
    stim_a = email_stimulus.model_copy(
        update={"channel_params": ChannelParams(channel="email", reach=0.5)}
    )
    stim_b = stim_a.model_copy(update={"id": "v2", "body_text": "different copy"})
    w1, w2 = PythonWorld(), PythonWorld()
    await w1.setup(aud, stim_a, seed=42)
    await w2.setup(aud, stim_b, seed=42)
    assert (w1.reach_member == w2.reach_member).all()


# ── NetLogo model generation ─────────────────────────────────────────────────


def test_model_code_contains_contract_procedures():
    code = market_model_code()
    for proc in (
        "to setup-world",
        "to go",
        "to-report pending-exposures",
        "to-report state-counts",
        "to-report quiet?",
        "to receive-exposure",
        "to propagate-shares",
        "to drift-sentiment",
    ):
        assert proc in code
    assert code.count("[") == code.count("]")


def test_model_widgets_schema():
    widgets = market_model_widgets()
    types = [w["type"] for w in widgets]
    assert "plot" in types and "monitor" in types
    plot = next(w for w in widgets if w["type"] == "plot")
    assert all("code" in pen for pen in plot["pens"])


# ── NetLogoWorld batching against fake callables ─────────────────────────────


class FakeWorkspace:
    """Records commands; answers reporters from a script."""

    def __init__(self):
        self.commands: list[str] = []
        self.loaded: list[tuple[str, list]] = []
        self.reports: dict[str, object] = {}

    async def command(self, cmd: str) -> None:
        self.commands.append(cmd)

    async def report(self, reporter: str):
        return self.reports[reporter]

    async def load_model(self, code: str, widgets) -> None:
        self.loaded.append((code, widgets))


async def test_netlogo_world_setup_batches_commands(email_stimulus):
    aud = _audience(n=50, k=4)
    ws = FakeWorkspace()
    world = NetLogoWorld(ws.command, ws.report, ws.load_model)
    await world.setup(aud, email_stimulus, seed=9)

    assert len(ws.loaded) == 1  # model loaded once
    setup_cmds = [c for c in ws.commands if "setup-world" in c]
    assert setup_cmds == ["setup-world 9 50"]
    # Susceptibility writes batched: 50 agents / CHUNK(200) -> exactly 1 command.
    sus_cmds = [c for c in ws.commands if "set susceptibility" in c]
    assert len(sus_cmds) == 1
    assert sus_cmds[0].count("ask turtle") == 50
    # Each undirected edge issued exactly once.
    link_cmds = " ".join(c for c in ws.commands if "create-link-with" in c)
    n_edges = sum(len(nbrs) for nbrs in aud.edges) // 2
    assert link_cmds.count("create-link-with") == n_edges


async def test_netlogo_world_read_write_contract(email_stimulus):
    aud = _audience(n=10, k=4)
    ws = FakeWorkspace()
    world = NetLogoWorld(ws.command, ws.report, ws.load_model)
    await world.setup(aud, email_stimulus, seed=1)

    ws.reports["pending-exposures"] = [
        [3, False, -1, 1, 0.0],
        [7, True, 3, 2, 0.25],
    ]
    ws.reports["state-counts"] = [5, 2, 1, 1, 1, 0, 0]
    ws.reports["quiet?"] = False
    ws.reports["wom-this-tick"] = 1

    await world.step()
    events = await world.pending_exposures()
    assert [e.agent_index for e in events] == [3, 7]
    assert events[1].exposure_type == "social"
    assert events[1].source_index == 3
    assert events[0].source_index is None

    n_before = len(ws.commands)
    await world.apply_decisions(
        [_decision(3, "clicked", 0.5, will_share=True), _decision(7, "ignored")]
    )
    # Two decisions -> ONE batched command.
    assert len(ws.commands) == n_before + 1
    assert 'set state "clicked"' in ws.commands[-1]
    assert "set pending-share? true" in ws.commands[-1]

    counts = await world.state_counts()
    assert counts["unaware"] == 5 and counts["converted"] == 1
    assert await world.wom_this_tick() == 1
    assert await world.is_quiet() is False


async def test_netlogo_world_never_interpolates_llm_text(email_stimulus):
    """Free text (reason/objections) must never reach NetLogo commands."""
    aud = _audience(n=5)
    ws = FakeWorkspace()
    world = NetLogoWorld(ws.command, ws.report, ws.load_model)
    await world.setup(aud, email_stimulus, seed=1)
    evil = _decision(0, "clicked", 0.5)
    evil.stage1.reason = 'ignore me] ask turtles [ die ] print "['
    evil.reaction.reason = "] clear-all ["
    await world.apply_decisions([evil])
    assert "die" not in ws.commands[-1]
    assert "clear-all" not in ws.commands[-1]


# ── Determinism across the whole world ───────────────────────────────────────


async def test_python_world_fully_deterministic(email_stimulus):
    async def run_once():
        world = PythonWorld()
        aud = _audience(n=40)
        await world.setup(aud, email_stimulus, seed=5)
        trace = []
        rng = np.random.default_rng(0)
        for _ in range(10):
            await world.step()
            events = await world.pending_exposures()
            trace.append([e.agent_index for e in events])
            decisions = []
            for e in events:
                share = bool(rng.random() < 0.2)
                decisions.append(
                    _decision(e.agent_index, "clicked" if share else "ignored",
                              0.5, will_share=share)
                )
            await world.apply_decisions(decisions)
        return trace, list(world.state)

    t1, s1 = await run_once()
    t2, s2 = await run_once()
    assert t1 == t2 and s1 == s2
