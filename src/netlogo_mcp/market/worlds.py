"""World bridges — where the audience 'lives' during a campaign run.

Two implementations of one contract (``WorldBridge``):

- ``NetLogoWorld``  — turtles in the shared NetLogo workspace, driven through
  batched ``command``/``report`` calls (2 JVM hops per tick regardless of
  population size). Visible in the GUI; the demo path.
- ``PythonWorld``   — a pure-Python mirror of the exact same rules. No JVM,
  runs in CI, used by tests and validation scripts. Also the fallback engine
  when NetLogo isn't installed.

Shared semantics (any change must land in BOTH implementations AND in
``netlogo_gen.py``):

- 1 tick = 1 simulated hour.
- Direct delivery: ``email``/``organic`` deliver once at ``send_tick`` to all
  reach members; ``paid_social`` delivers ``impressions_per_tick x reach``
  impressions per tick from ``send_tick`` on, respecting ``frequency_cap``.
- Word of mouth: an agent whose decision sets ``will_share`` schedules an
  exposure for each receptive neighbor with a 1-5 tick delay.
- Receptive states: unaware / exposed / ignored / engaged. Converted, clicked
  and annoyed agents are not re-exposed.
- Sentiment drift (DeGroot): each tick agents move toward the mean sentiment
  of their non-unaware neighbors, weighted by ``susceptibility * 0.1``.
- Exposure marking flips ``unaware -> exposed``; every other funnel move
  comes exclusively from cognition decisions.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from .schemas import Audience, Decision, ExposureEvent, Stimulus

RECEPTIVE = frozenset({"unaware", "exposed", "ignored", "engaged"})
STATES = (
    "unaware",
    "exposed",
    "engaged",
    "clicked",
    "converted",
    "ignored",
    "annoyed",
)

WOM_DELAY_MAX = 5  # scheduled share lands 1..5 ticks later


class WorldBridge(Protocol):
    """One replicate-run's simulation world."""

    async def setup(self, audience: Audience, stimulus: Stimulus, seed: int) -> None: ...
    async def step(self) -> int: ...
    async def pending_exposures(self) -> list[ExposureEvent]: ...
    async def apply_decisions(self, decisions: list[Decision]) -> None: ...
    async def state_counts(self) -> dict[str, int]: ...
    async def wom_this_tick(self) -> int: ...
    async def is_quiet(self) -> bool: ...
    async def teardown(self) -> None: ...


# ── Pure-Python world ────────────────────────────────────────────────────────


class PythonWorld:
    """Reference implementation of the world rules. Deterministic per seed."""

    def __init__(self) -> None:
        self._tick = 0

    async def setup(self, audience: Audience, stimulus: Stimulus, seed: int) -> None:
        n = audience.size
        cp = stimulus.channel_params
        self.audience = audience
        self.stimulus = stimulus
        self.rng = np.random.default_rng(seed)
        self._tick = 0

        self.state = ["unaware"] * n
        self.sentiment = np.zeros(n)
        self.susceptibility = np.array([p.susceptibility for p in audience.personas])
        self.exposure_count = np.zeros(n, dtype=int)
        self.pending: dict[int, tuple[str, int | None]] = {}  # idx -> (type, source)
        self.scheduled: list[tuple[int, int, int]] = []  # (fire_tick, target, source)
        self.pending_share: set[int] = set()
        self.shared: set[int] = set()
        self.reach_member = self.rng.random(n) < cp.reach
        self.channel = cp.channel
        self.send_tick = cp.send_tick
        self.impressions_per_tick = cp.impressions_per_tick
        self.frequency_cap = cp.frequency_cap
        self._wom_this_tick = 0
        self._wom_total = 0

    # -- rules ----------------------------------------------------------------

    def _receptive(self, i: int) -> bool:
        return self.state[i] in RECEPTIVE

    def _expose(self, i: int, social: bool, source: int | None) -> None:
        if i in self.pending:
            return
        self.pending[i] = ("social" if social else "direct", source)
        self.exposure_count[i] += 1
        if self.state[i] == "unaware":
            self.state[i] = "exposed"
        if social:
            self._wom_this_tick += 1
            self._wom_total += 1

    def _deliver_direct(self) -> None:
        if self.channel in ("email", "organic"):
            if self._tick == self.send_tick:
                for i in range(self.audience.size):
                    if self.reach_member[i] and self._receptive(i):
                        self._expose(i, False, None)
        elif self.channel == "paid_social" and self._tick >= self.send_tick:
            eligible = [
                i
                for i in range(self.audience.size)
                if self.reach_member[i]
                and self._receptive(i)
                and self.exposure_count[i] < self.frequency_cap
                and i not in self.pending
            ]
            n_imp = round(self.impressions_per_tick * int(self.reach_member.sum()))
            n_imp = min(n_imp, len(eligible))
            if n_imp > 0:
                picks = self.rng.choice(len(eligible), size=n_imp, replace=False)
                for j in picks:
                    self._expose(eligible[int(j)], False, None)

    def _fire_scheduled(self) -> None:
        due = [s for s in self.scheduled if s[0] <= self._tick]
        self.scheduled = [s for s in self.scheduled if s[0] > self._tick]
        for _, target, source in due:
            if (
                self._receptive(target)
                and self.exposure_count[target] < self.frequency_cap
                and target not in self.pending
            ):
                self._expose(target, True, source)

    def _propagate_shares(self) -> None:
        for src in sorted(self.pending_share):
            for nbr in self.audience.edges[src]:
                if self._receptive(nbr) and self.exposure_count[nbr] < self.frequency_cap:
                    delay = 1 + int(self.rng.integers(0, WOM_DELAY_MAX))
                    self.scheduled.append((self._tick + delay, nbr, src))
            self.shared.add(src)
        self.pending_share.clear()

    def _drift_sentiment(self) -> None:
        new = self.sentiment.copy()
        for i in range(self.audience.size):
            opinions = [
                self.sentiment[j]
                for j in self.audience.edges[i]
                if self.state[j] != "unaware"
            ]
            if opinions:
                w = self.susceptibility[i] * 0.1
                new[i] = self.sentiment[i] + w * (
                    float(np.mean(opinions)) - self.sentiment[i]
                )
        self.sentiment = new

    # -- WorldBridge API --------------------------------------------------------

    async def step(self) -> int:
        self._wom_this_tick = 0
        self._tick += 1
        self._deliver_direct()
        self._fire_scheduled()
        self._propagate_shares()
        self._drift_sentiment()
        return self._tick

    async def pending_exposures(self) -> list[ExposureEvent]:
        events = []
        for i in sorted(self.pending):
            etype, source = self.pending[i]
            events.append(
                ExposureEvent(
                    agent_index=i,
                    exposure_type=etype,  # type: ignore[arg-type]
                    source_index=source,
                    prior_sentiment=float(np.clip(self.sentiment[i], -1, 1)),
                    exposure_count=int(self.exposure_count[i]),
                    tick=self._tick,
                )
            )
        return events

    async def apply_decisions(self, decisions: list[Decision]) -> None:
        for d in decisions:
            i = d.agent_index
            self.state[i] = d.state
            self.sentiment[i] = d.sentiment
            self.pending.pop(i, None)
            if d.will_share and i not in self.shared:
                self.pending_share.add(i)

    async def state_counts(self) -> dict[str, int]:
        counts = dict.fromkeys(STATES, 0)
        for s in self.state:
            counts[s] += 1
        return counts

    async def wom_this_tick(self) -> int:
        return self._wom_this_tick

    async def is_quiet(self) -> bool:
        if self.pending or self.scheduled or self.pending_share:
            return False
        if self.channel in ("email", "organic"):
            return self._tick >= self.send_tick
        # paid_social keeps buying impressions while anyone is reachable.
        return not any(
            self.reach_member[i]
            and self._receptive(i)
            and self.exposure_count[i] < self.frequency_cap
            for i in range(self.audience.size)
        )

    async def teardown(self) -> None:  # nothing to release
        return None


# ── NetLogo-backed world ─────────────────────────────────────────────────────


class NetLogoWorld:
    """Drives the generated market_sim model in the shared workspace.

    Decoupled from MCP internals: the caller injects two async callables —
    ``command(str)`` and ``report(str) -> Any`` — plus ``load_model(code,
    widgets)`` which (re)loads the generated model. ``market/tools.py`` wires
    these to the existing workspace helpers.

    Batching contract: one ``report`` to read all pending exposures, one
    ``command`` to write all decisions — never per-agent JVM hops.
    """

    # Values written back into NetLogo come only from validated Pydantic
    # fields (Literal states, clamped floats) — no LLM text ever crosses.

    CHUNK = 200  # agents/edges per setup command string

    def __init__(self, command, report, load_model) -> None:
        self._command = command
        self._report = report
        self._load_model = load_model
        self._tick = 0

    async def setup(self, audience: Audience, stimulus: Stimulus, seed: int) -> None:
        from .netlogo_gen import market_model_code, market_model_widgets

        self.audience = audience
        self.stimulus = stimulus
        self._tick = 0
        cp = stimulus.channel_params

        await self._load_model(
            market_model_code(), market_model_widgets()
        )
        # setup-world's clear-all wipes globals, so campaign params are set
        # afterwards via configure-campaign (same command, ordered).
        await self._command(
            f"setup-world {seed} {audience.size} "
            f'configure-campaign "{cp.channel}" {cp.send_tick} {cp.reach} '
            f"{cp.impressions_per_tick} {cp.frequency_cap}"
        )

        # Per-turtle susceptibility, batched.
        sets = [
            f"ask turtle {i} [ set susceptibility {p.susceptibility:.4f} ]"
            for i, p in enumerate(audience.personas)
        ]
        for chunk_start in range(0, len(sets), self.CHUNK):
            await self._command(" ".join(sets[chunk_start : chunk_start + self.CHUNK]))

        # Social links (each undirected edge once), batched.
        links = [
            f"ask turtle {i} [ create-link-with turtle {j} ]"
            for i, nbrs in enumerate(audience.edges)
            for j in nbrs
            if j > i
        ]
        for chunk_start in range(0, len(links), self.CHUNK):
            await self._command(
                " ".join(links[chunk_start : chunk_start + self.CHUNK])
            )
        if audience.size <= 300:
            await self._command(
                "repeat 30 [ layout-spring turtles links 0.2 4 1 ] "
                "ask turtles [ setxy 0.95 * xcor 0.95 * ycor ]"
            )

    async def step(self) -> int:
        await self._command("go")
        self._tick += 1
        return self._tick

    async def pending_exposures(self) -> list[ExposureEvent]:
        raw = await self._report("pending-exposures")
        events: list[ExposureEvent] = []
        for row in list(raw) if raw is not None else []:
            row = list(row)
            who = int(row[0])
            social = bool(int(row[1]))  # NetLogo encodes exp-social? as 1/0
            source = int(row[2])
            events.append(
                ExposureEvent(
                    agent_index=who,
                    exposure_type="social" if social else "direct",
                    source_index=source if source >= 0 else None,
                    prior_sentiment=float(max(-1.0, min(1.0, float(row[4])))),
                    exposure_count=max(1, int(row[3])),
                    tick=self._tick,
                )
            )
        return events

    async def apply_decisions(self, decisions: list[Decision]) -> None:
        if not decisions:
            return
        parts = []
        for d in decisions:
            share = "true" if d.will_share else "false"
            parts.append(
                f'ask turtle {d.agent_index} [ set state "{d.state}" '
                f"set sentiment {d.sentiment:.4f} set pending-share? {share} "
                "set exposure-pending? false ]"
            )
        for chunk_start in range(0, len(parts), self.CHUNK):
            await self._command(
                " ".join(parts[chunk_start : chunk_start + self.CHUNK])
            )

    async def state_counts(self) -> dict[str, int]:
        raw = await self._report("state-counts")
        values = [int(v) for v in list(raw)]
        return dict(zip(STATES, values, strict=False))

    async def wom_this_tick(self) -> int:
        return int(await self._report("wom-this-tick"))

    async def is_quiet(self) -> bool:
        return bool(await self._report("quiet?"))

    async def teardown(self) -> None:  # model stays loaded for inspection
        return None


def _unused(*_: Any) -> None:  # pragma: no cover
    return None
