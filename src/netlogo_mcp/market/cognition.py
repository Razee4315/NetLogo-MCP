"""Cognition Engine — resolves exposure events into persona decisions.

Two interchangeable backends:

- ``LLMBackend``       — real persona cognition via any OpenAI-compatible
                         endpoint (Ollama, llama.cpp server, cloud). Used when
                         ``SYNTH_LLM_MODE=live``.
- ``HeuristicBackend`` — deterministic, persona-driven rule model. The
                         default until a local LLM is installed, the test
                         double, and the "no-LLM baseline" for ablations.

On top of the backend, ``CognitionEngine`` adds the cost machinery:

- exact response cache (SQLite) — re-running a tweaked campaign only pays
  for changed exposures;
- archetype response distributions — in ``fast``/``mixed`` fidelity the
  backend runs a few times per archetype and individual agents sample from
  that distribution instead of paying their own call;
- bounded concurrency (semaphore sized to the endpoint's parallelism).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import time
from typing import Any, Protocol

import numpy as np
from pydantic import ValidationError

from . import prompts
from .archetypes import representative_indices
from .config import LLMConfig, get_cache_dir, get_llm_config
from .schemas import (
    Audience,
    Decision,
    ExposureEvent,
    Persona,
    Reaction,
    Stage1Decision,
    Stimulus,
    resolve_state,
)

logger = logging.getLogger("netlogo_mcp.market.cognition")

_CHANNEL_FOR_TYPE = {
    "email": "email",
    "social_ad": "paid_social",
    "landing_page": "organic",
    "search_ad": "paid_social",
}

# ── LLM transport (OpenAI-compatible; Ollama's /v1 endpoint qualifies) ───────


def _extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object out of model output, tolerating code fences and
    surrounding chatter."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


class OpenAICompatClient:
    """Minimal async chat-completions client with structured-output fallback.

    Tries ``response_format: json_schema`` first (best), degrades to
    ``json_object``, then to nothing — remembering what worked so each run
    probes at most twice. The schema is always ALSO described in the prompt,
    so degraded modes still produce parseable output.
    """

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self._format_mode: str | None = None  # "json_schema"|"json_object"|"none"
        import httpx

        self._client = httpx.AsyncClient(
            base_url=cfg.base_url,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=cfg.timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _response_format(self, schema: dict | None, mode: str) -> dict | None:
        if schema is None or mode == "none":
            return None
        if mode == "json_object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {"name": "response", "schema": schema, "strict": True},
        }

    async def chat(
        self,
        system: str,
        user: str,
        schema: dict | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        max_tokens: int = 500,
    ) -> str:
        """Return the raw assistant message content."""
        modes = (
            [self._format_mode]
            if self._format_mode
            else ["json_schema", "json_object", "none"]
        )
        last_error: Exception | None = None
        for mode in modes:
            body: dict[str, Any] = {
                "model": self.cfg.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": (
                    self.cfg.temperature if temperature is None else temperature
                ),
                "max_tokens": max_tokens,
            }
            if seed is not None:
                body["seed"] = seed
            fmt = self._response_format(schema, mode)
            if fmt is not None:
                body["response_format"] = fmt
            try:
                resp = await self._client.post("/chat/completions", json=body)
                if resp.status_code == 400 and mode != "none":
                    # Endpoint doesn't support this response_format — degrade.
                    last_error = RuntimeError(f"400 with format={mode}: {resp.text[:200]}")
                    continue
                resp.raise_for_status()
                data = resp.json()
                self._format_mode = mode
                return str(data["choices"][0]["message"]["content"])
            except Exception as e:  # noqa: BLE001 — retried by tenacity upstream
                last_error = e
                if mode == modes[-1]:
                    raise
        raise last_error or RuntimeError("LLM request failed")


# ── Backend protocol ─────────────────────────────────────────────────────────


class CognitionBackend(Protocol):
    async def stage1(
        self,
        persona: Persona,
        stimulus: Stimulus,
        event: ExposureEvent,
        source: Persona | None,
        seed: int,
    ) -> Stage1Decision: ...

    async def stage2(
        self, persona: Persona, stimulus: Stimulus, event: ExposureEvent, seed: int
    ) -> Reaction: ...

    async def interview(
        self, persona: Persona, question: str, stimulus: Stimulus | None
    ) -> str: ...


# ── LLM backend ──────────────────────────────────────────────────────────────


class LLMBackend:
    """Persona cognition through a live model."""

    def __init__(self, cfg: LLMConfig | None = None) -> None:
        self.cfg = cfg or get_llm_config()
        self.client = OpenAICompatClient(self.cfg)
        self.calls = 0

    async def _structured(
        self,
        persona: Persona,
        user: str,
        schema: dict,
        seed: int,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Chat + parse, with one corrective retry on bad JSON/validation."""
        from tenacity import (
            retry,
            stop_after_attempt,
            wait_exponential,
        )

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, max=8),
            reraise=True,
        )
        async def _call(prompt: str) -> str:
            self.calls += 1
            return await self.client.chat(
                system=prompts.render_system(persona),
                user=prompt,
                schema=schema,
                seed=seed,
                max_tokens=max_tokens,
            )

        raw = await _call(user)
        try:
            return _extract_json(raw)
        except (json.JSONDecodeError, ValueError):
            fixed = await _call(
                user
                + "\n\nYour previous reply was not valid JSON. Reply with ONLY "
                "the JSON object, no prose, no code fences."
            )
            return _extract_json(fixed)

    async def stage1(
        self,
        persona: Persona,
        stimulus: Stimulus,
        event: ExposureEvent,
        source: Persona | None,
        seed: int,
    ) -> Stage1Decision:
        data = await self._structured(
            persona,
            prompts.render_stage1(persona, stimulus, event, source),
            prompts.STAGE1_SCHEMA,
            seed,
            max_tokens=200,
        )
        try:
            return Stage1Decision(**data)
        except ValidationError:
            action = str(data.get("action", "scroll_past")).lower().strip()
            if action not in ("open", "scroll_past", "delete"):
                action = "scroll_past"
            return Stage1Decision(
                action=action,  # type: ignore[arg-type]
                reason=str(data.get("reason", ""))[:400],
            )

    async def stage2(
        self, persona: Persona, stimulus: Stimulus, event: ExposureEvent, seed: int
    ) -> Reaction:
        data = await self._structured(
            persona,
            prompts.render_stage2(stimulus),
            prompts.STAGE2_SCHEMA,
            seed,
            max_tokens=500,
        )
        # Clamp numerics instead of failing an otherwise-usable response.
        def _clip(v: Any, lo: float, hi: float, default: float) -> float:
            try:
                return float(min(hi, max(lo, float(v))))
            except (TypeError, ValueError):
                return default

        data["sentiment"] = _clip(data.get("sentiment"), -1, 1, 0.0)
        data["trust_delta"] = _clip(data.get("trust_delta", 0), -1, 1, 0.0)
        data["attention_seconds"] = int(
            _clip(data.get("attention_seconds", 10), 0, 300, 10)
        )
        if not isinstance(data.get("objections"), list):
            data["objections"] = []
        data.setdefault("would_share_with", "nobody")
        try:
            return Reaction(**data)
        except ValidationError:
            return Reaction(
                attention_seconds=int(data["attention_seconds"]),
                action="ignore",
                sentiment=float(data["sentiment"]),
                reason=str(data.get("reason", ""))[:600],
            )

    async def interview(
        self, persona: Persona, question: str, stimulus: Stimulus | None
    ) -> str:
        self.calls += 1
        return await self.client.chat(
            system=prompts.render_system(persona),
            user=prompts.render_interview(question, stimulus),
            schema=None,
            max_tokens=300,
        )


# ── Heuristic (mock) backend ─────────────────────────────────────────────────

_SPAM_TOKENS = (
    "free",
    "act now",
    "limited time",
    "!!!",
    "100%",
    "guarantee",
    "winner",
    "$$$",
    "click here",
    "don't miss",
)


def _rng_for(*parts: Any) -> np.random.Generator:
    blob = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(blob.encode("utf-8")).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "little"))


def _word_overlap(text: str, phrases: list[str]) -> float:
    words = set(re.findall(r"[a-z]{4,}", text.lower()))
    if not words or not phrases:
        return 0.0
    hits = sum(
        1 for ph in phrases if any(w in words for w in re.findall(r"[a-z]{4,}", ph.lower()))
    )
    return hits / max(1, len(phrases))


def _spamminess(text: str) -> float:
    t = text.lower()
    score = sum(0.15 for tok in _SPAM_TOKENS if tok in t)
    caps_words = re.findall(r"\b[A-Z]{4,}\b", text)
    score += 0.1 * len(caps_words)
    if text.count("!") >= 2:
        score += 0.15
    return min(1.0, score)


class HeuristicBackend:
    """Deterministic persona-driven reaction model. No LLM, no network.

    Not a toy: every probability is a function of the persona's structured
    traits and observable stimulus properties, so populations produce
    *differentiated, plausible* aggregate behavior. Serves as (a) the default
    engine until a local LLM is installed, (b) the test double, and (c) the
    rule-based baseline the LLM must beat in validation.
    """

    def __init__(self, salt: int = 0) -> None:
        self.salt = salt
        self.calls = 0

    # -- stage 1 ------------------------------------------------------------

    def _open_probability(
        self, persona: Persona, stimulus: Stimulus, event: ExposureEvent
    ) -> float:
        teaser = stimulus.teaser_text() or stimulus.body_text[:200]
        channel = _CHANNEL_FOR_TYPE.get(stimulus.type, "email")
        if event.exposure_type == "social":
            base = 0.25 + 0.35 * persona.susceptibility
            if event.prior_sentiment > 0:
                base += 0.1
        else:
            base = 0.12 + 0.38 * persona.channel_propensity(channel)
        p = base
        p += 0.18 * (persona.category_involvement - 0.5)
        p += 0.10 * (persona.trust_in_ads - 0.3)
        p += 0.08 * (persona.novelty_seeking - 0.5)
        p += 0.15 * _word_overlap(teaser, persona.pain_points + persona.values)
        p -= _spamminess(teaser) * (1.0 - persona.trust_in_ads) * 0.35
        subject = stimulus.teaser.get("subject") or stimulus.teaser.get("headline", "")
        if subject and 20 <= len(subject) <= 65:
            p += 0.04
        p -= 0.12 * (event.exposure_count - 1)  # fatigue
        return float(min(0.92, max(0.02, p)))

    async def stage1(
        self,
        persona: Persona,
        stimulus: Stimulus,
        event: ExposureEvent,
        source: Persona | None,
        seed: int,
    ) -> Stage1Decision:
        self.calls += 1
        rng = _rng_for(
            "s1", self.salt, seed, persona.cache_key(), stimulus.cache_key(),
            event.exposure_type, event.exposure_count,
        )
        p_open = self._open_probability(persona, stimulus, event)
        teaser = stimulus.teaser_text()
        spam = _spamminess(teaser)
        if rng.random() < p_open:
            reason = (
                "A friend passed this along, so I gave it a look."
                if event.exposure_type == "social"
                else "The subject touched on something I actually care about, so I opened it."
            )
            return Stage1Decision(action="open", reason=reason)
        if spam > 0.3 and persona.trust_in_ads < 0.35 and rng.random() < 0.5:
            return Stage1Decision(
                action="delete",
                reason="Looked like classic marketing bait — deleted without opening.",
            )
        if event.exposure_count > 1 and rng.random() < 0.3:
            return Stage1Decision(
                action="delete",
                reason="Same message again — I'm starting to find this brand annoying.",
            )
        return Stage1Decision(
            action="scroll_past",
            reason="Nothing about it grabbed me; I moved on without thinking.",
        )

    # -- stage 2 ------------------------------------------------------------

    def _interest(self, persona: Persona, stimulus: Stimulus) -> float:
        body = f"{stimulus.body_text} {stimulus.cta}"
        interest = 0.0
        interest += 0.40 * persona.category_involvement
        interest += 0.12 * persona.novelty_seeking
        interest += 0.12 * persona.trust_in_ads
        interest += 0.15 * _word_overlap(body, persona.pain_points + persona.values)
        if stimulus.offer:
            interest += 0.15 * persona.price_sensitivity
        if stimulus.price_shown:
            interest += 0.05
        else:
            interest -= 0.12 * persona.price_sensitivity  # hidden price = distrust
        interest -= 0.15 * _spamminess(body) * (1.0 - persona.trust_in_ads)
        interest -= 0.10 * persona.brand_loyalty * (
            1.0 if "competitor" in persona.current_solution else 0.3
        )
        return float(min(1.0, max(0.0, interest)))

    def _objections(self, persona: Persona, stimulus: Stimulus) -> list[str]:
        out: list[str] = []
        if persona.price_sensitivity > 0.6 and not stimulus.price_shown:
            out.append("no clear price — that makes me suspicious")
        if persona.trust_in_ads < 0.3:
            out.append("sounds too good to be true")
        if persona.objection_style == "loyalist":
            out.append(f"I already use {persona.current_solution} and it's fine")
        if persona.objection_style == "skeptic" and stimulus.offer:
            out.append("discounts this big usually mean a catch in the fine print")
        if persona.price_sensitivity > 0.6 and stimulus.price_shown:
            out.append("the ongoing price is more than I want to commit to")
        return out[:3]

    async def stage2(
        self, persona: Persona, stimulus: Stimulus, event: ExposureEvent, seed: int
    ) -> Reaction:
        self.calls += 1
        rng = _rng_for(
            "s2", self.salt, seed, persona.cache_key(), stimulus.cache_key(),
            event.exposure_type,
        )
        interest = self._interest(persona, stimulus)

        p_buy = max(0.0, (interest - 0.55)) * 0.35 * (1.0 - 0.5 * persona.price_sensitivity)
        p_click = max(0.0, interest - 0.25) * 0.55
        p_save = max(0.0, interest - 0.30) * 0.15 * persona.personality.conscientiousness
        p_share = (
            max(0.0, interest - 0.40)
            * 0.4
            * persona.personality.extraversion
            * persona.influence
        )
        p_annoy = (
            0.10
            * (1.0 - persona.trust_in_ads)
            * (1.0 if event.exposure_count > 1 else 0.4)
        )

        r = rng.random()
        cumulative = 0.0
        action = "ignore"
        for candidate, p in (
            ("buy", p_buy),
            ("share", p_share),
            ("click", p_click),
            ("save_for_later", p_save),
            ("unsubscribe", p_annoy),
        ):
            cumulative += p
            if r < cumulative:
                action = candidate
                break

        sentiment = float(
            min(1.0, max(-1.0, (interest - 0.45) * 1.8 + rng.normal(0, 0.15)))
        )
        if action in ("unsubscribe", "report_spam"):
            sentiment = min(sentiment, -0.4)
        objections = self._objections(persona, stimulus)

        reasons = {
            "buy": "This lines up with something I've been meaning to fix, and the offer tips it.",
            "click": "Curious enough to look, but I'm not sold yet.",
            "save_for_later": "Interesting, but not a now thing — saving it.",
            "share": "This is exactly the kind of thing a couple of my friends keep complaining about.",
            "unsubscribe": "I didn't ask for this and it's not for me — unsubscribing.",
            "ignore": (
                objections[0]
                if objections and rng.random() < 0.7
                else "Read it, shrugged, moved on with my day."
            ),
        }
        would_share = "nobody"
        if action == "share":
            would_share = "publicly" if persona.influence > 0.6 else "close_friends"
        elif sentiment > 0.5 and persona.personality.extraversion > 0.6:
            would_share = "close_friends"

        return Reaction(
            attention_seconds=int(5 + interest * 60 + rng.integers(0, 15)),
            action=action,  # type: ignore[arg-type]
            sentiment=sentiment,
            trust_delta=float(min(1.0, max(-1.0, sentiment * 0.3))),
            reason=reasons[action],
            objections=objections if action in ("ignore", "unsubscribe") else objections[:1],
            would_share_with=would_share,  # type: ignore[arg-type]
        )

    async def interview(
        self, persona: Persona, question: str, stimulus: Stimulus | None
    ) -> str:
        self.calls += 1
        style = {
            "skeptic": "Honestly? My first instinct with anything like this is to look for the catch.",
            "pragmatist": "For me it comes down to whether it solves a real problem I have.",
            "enthusiast": "I do enjoy finding new things, so I gave it a fair shot.",
            "bargain-hunter": "The price is the first thing I look at, always.",
            "loyalist": f"I already rely on {persona.current_solution}, so the bar to switch is high.",
        }[persona.objection_style]
        pains = (
            f" What actually weighs on me day to day: {'; '.join(persona.pain_points[:2])}."
            if persona.pain_points
            else ""
        )
        return (
            f"{style}{pains} Asking me \"{question.strip()}\" — my honest answer is "
            "that it depends on whether it respects my time and is upfront about cost. "
            "(Note: heuristic backend — set SYNTH_LLM_MODE=live for real persona interviews.)"
        )


# ── Response cache ───────────────────────────────────────────────────────────


class ResponseCache:
    """SQLite-backed cache for backend responses and archetype distributions."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or str(get_cache_dir() / "responses.sqlite")
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS responses ("
            " key TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL)"
        )
        self._conn.commit()

    def get(self, key: str) -> Any | None:
        row = self._conn.execute(
            "SELECT payload FROM responses WHERE key = ?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, payload: Any) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO responses (key, payload, created) VALUES (?,?,?)",
            (key, json.dumps(payload), time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


# ── Engine ───────────────────────────────────────────────────────────────────


def _serialize_pair(s1: Stage1Decision, r2: Reaction | None) -> dict[str, Any]:
    return {"stage1": s1.model_dump(), "reaction": r2.model_dump() if r2 else None}


def _deserialize_pair(data: dict[str, Any]) -> tuple[Stage1Decision, Reaction | None]:
    s1 = Stage1Decision(**data["stage1"])
    r2 = Reaction(**data["reaction"]) if data.get("reaction") else None
    return s1, r2


class CognitionEngine:
    """Resolves exposure events for one audience, with caching + fidelity."""

    def __init__(
        self,
        audience: Audience,
        backend: CognitionBackend | None = None,
        fidelity: str = "mixed",
        full_fidelity_sample: int = 150,
        archetype_draws: int = 5,
        seed: int = 0,
        cache: ResponseCache | None = None,
        concurrency: int | None = None,
        use_cache: bool = True,
    ) -> None:
        cfg = get_llm_config()
        if backend is None:
            backend = LLMBackend(cfg) if cfg.mode == "live" else HeuristicBackend()
        self.audience = audience
        self.backend = backend
        self.fidelity = fidelity
        self.archetype_draws = max(1, archetype_draws)
        self.seed = seed
        self.use_cache = use_cache
        self.cache = cache or ResponseCache()
        self._sem = asyncio.Semaphore(concurrency or cfg.concurrency)
        self._dist_locks: dict[str, asyncio.Lock] = {}
        self.llm_calls = 0
        self.cache_hits = 0

        if fidelity == "full":
            self._full_idx: set[int] = set(range(audience.size))
        elif fidelity == "fast":
            self._full_idx = set()
        else:  # mixed
            has_archetypes = any(p.archetype >= 0 for p in audience.personas)
            if not has_archetypes:
                self._full_idx = set(range(audience.size))
            else:
                self._full_idx = set(
                    representative_indices(audience, full_fidelity_sample, seed=seed)
                )

    # -- internals -----------------------------------------------------------

    def _persona(self, idx: int) -> Persona:
        return self.audience.personas[idx]

    def _context_hash(self, event: ExposureEvent) -> str:
        blob = f"{event.exposure_type}|{min(event.exposure_count, 3)}|{event.source_comment[:80]}"
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:10]

    async def _run_backend(
        self, persona: Persona, stimulus: Stimulus, event: ExposureEvent, seed: int
    ) -> tuple[Stage1Decision, Reaction | None, int]:
        source = (
            self._persona(event.source_index)
            if event.source_index is not None
            and 0 <= event.source_index < self.audience.size
            else None
        )
        calls = 0
        async with self._sem:
            s1 = await self.backend.stage1(persona, stimulus, event, source, seed)
            calls += 1
            r2: Reaction | None = None
            if s1.action == "open":
                r2 = await self.backend.stage2(persona, stimulus, event, seed)
                calls += 1
        return s1, r2, calls

    async def _individual(
        self, persona: Persona, stimulus: Stimulus, event: ExposureEvent
    ) -> tuple[Stage1Decision, Reaction | None, bool, int]:
        key = (
            f"full:{persona.cache_key()}:{stimulus.cache_key()}:"
            f"{self._context_hash(event)}:{self.seed}"
        )
        if self.use_cache:
            hit = self.cache.get(key)
            if hit is not None:
                self.cache_hits += 1
                s1, r2 = _deserialize_pair(hit)
                return s1, r2, True, 0
        s1, r2, calls = await self._run_backend(
            persona, stimulus, event, seed=self.seed + event.agent_index
        )
        if self.use_cache:
            self.cache.put(key, _serialize_pair(s1, r2))
        return s1, r2, False, calls

    async def _from_archetype(
        self, persona: Persona, stimulus: Stimulus, event: ExposureEvent
    ) -> tuple[Stage1Decision, Reaction | None, bool, int]:
        arch = persona.archetype
        key = (
            f"arch:{self.audience.spec.name}:{arch}:{stimulus.cache_key()}:"
            f"{self._context_hash(event)}:{self.seed}"
        )
        dist = self.cache.get(key) if self.use_cache else None
        calls = 0
        if dist is None:
            lock = self._dist_locks.setdefault(key, asyncio.Lock())
            async with lock:
                dist = self.cache.get(key) if self.use_cache else None
                if dist is None:
                    members = self.audience.archetype_members().get(arch, [])
                    rep = self._persona(members[0]) if members else persona
                    draws = []
                    for d in range(self.archetype_draws):
                        s1, r2, c = await self._run_backend(
                            rep, stimulus, event, seed=self.seed * 1000 + arch * 10 + d
                        )
                        calls += c
                        draws.append(_serialize_pair(s1, r2))
                    dist = draws
                    if self.use_cache:
                        self.cache.put(key, dist)
        else:
            self.cache_hits += 1
        rng = _rng_for("draw", self.seed, event.agent_index, stimulus.cache_key(),
                       self._context_hash(event))
        s1, r2 = _deserialize_pair(dist[int(rng.integers(0, len(dist)))])
        return s1, r2, calls == 0, calls

    # -- public API ----------------------------------------------------------

    async def decide(self, event: ExposureEvent, stimulus: Stimulus) -> Decision:
        persona = self._persona(event.agent_index)
        use_individual = (
            event.agent_index in self._full_idx or persona.archetype < 0
        )
        if use_individual:
            s1, r2, cached, calls = await self._individual(persona, stimulus, event)
        else:
            s1, r2, cached, calls = await self._from_archetype(
                persona, stimulus, event
            )
        self.llm_calls += calls
        state = resolve_state(s1, r2)
        will_share = bool(
            r2 and (r2.action == "share" or r2.would_share_with == "publicly")
        )
        return Decision(
            agent_index=event.agent_index,
            persona_id=persona.id,
            stimulus_id=stimulus.id,
            tick=event.tick,
            exposure_type=event.exposure_type,
            stage1=s1,
            reaction=r2,
            state=state,
            will_share=will_share,
            cached=cached,
            llm_calls=calls,
        )

    async def decide_batch(
        self, events: list[ExposureEvent], stimulus: Stimulus
    ) -> list[Decision]:
        return list(
            await asyncio.gather(*(self.decide(ev, stimulus) for ev in events))
        )

    async def interview(
        self, persona_index: int, question: str, stimulus: Stimulus | None = None
    ) -> str:
        persona = self._persona(persona_index)
        async with self._sem:
            return await self.backend.interview(persona, question, stimulus)
