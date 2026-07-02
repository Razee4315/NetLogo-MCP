"""Pydantic models for the market simulation.

Three families:

1. **Population** — ``Persona``, ``AudienceSpec``, ``Audience``: who the
   synthetic customers are.
2. **Stimulus** — ``Stimulus``, ``CampaignSpec``: what they are shown.
3. **Cognition** — ``Stage1Decision``, ``Reaction``, ``ExposureEvent``,
   ``Decision``: how a persona's LLM response is represented and what gets
   written back into the simulation.

Only plain JSON-serializable types cross the LLM or NetLogo boundary; the
LLM's free text (``reason``, ``objections``) is stored in the event store and
NEVER interpolated into NetLogo code.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ── Funnel vocabulary ────────────────────────────────────────────────────────

FunnelState = Literal[
    "unaware",  # never exposed
    "exposed",  # stimulus reached them, not yet processed / bounced at gate
    "engaged",  # opened / viewed the full content
    "clicked",  # clicked through
    "converted",  # bought / signed up
    "ignored",  # saw it, moved on
    "annoyed",  # unsubscribed or reported spam
]

Stage1Action = Literal["open", "scroll_past", "delete"]

ReactionAction = Literal[
    "ignore",
    "click",
    "save_for_later",
    "buy",
    "share",
    "unsubscribe",
    "report_spam",
]

# How a stage-2 action maps onto the funnel. ``share`` implies a click-through
# (you read it and passed it on); ``save_for_later`` is engagement without a
# click this tick.
ACTION_TO_STATE: dict[str, str] = {
    "ignore": "ignored",
    "click": "clicked",
    "save_for_later": "engaged",
    "buy": "converted",
    "share": "clicked",
    "unsubscribe": "annoyed",
    "report_spam": "annoyed",
}

FUNNEL_ORDER: tuple[str, ...] = (
    "unaware",
    "exposed",
    "engaged",
    "clicked",
    "converted",
)


# ── Population ───────────────────────────────────────────────────────────────


class BigFive(BaseModel):
    """OCEAN personality traits, each in [0, 1]."""

    openness: float = Field(0.5, ge=0.0, le=1.0)
    conscientiousness: float = Field(0.5, ge=0.0, le=1.0)
    extraversion: float = Field(0.5, ge=0.0, le=1.0)
    agreeableness: float = Field(0.5, ge=0.0, le=1.0)
    neuroticism: float = Field(0.5, ge=0.0, le=1.0)


class Persona(BaseModel):
    """One synthetic customer. Layers 1-4 are structured and sampled from
    distributions; layer 5 (``persona_card``) is the narrative the LLM sees."""

    id: str

    # Layer 1 — demographics
    age: int = Field(ge=13, le=100)
    gender: str = "unspecified"
    location: str = "unspecified"
    income_bracket: Literal["low", "mid", "high"] = "mid"
    education: str = "unspecified"
    occupation: str = "unspecified"
    household: str = "unspecified"

    # Layer 2 — psychographics
    personality: BigFive = Field(default_factory=BigFive)
    values: list[str] = Field(default_factory=list)
    risk_tolerance: float = Field(0.5, ge=0.0, le=1.0)
    novelty_seeking: float = Field(0.5, ge=0.0, le=1.0)

    # Layer 3 — consumer profile
    category_involvement: float = Field(0.5, ge=0.0, le=1.0)
    price_sensitivity: float = Field(0.5, ge=0.0, le=1.0)
    brand_loyalty: float = Field(0.5, ge=0.0, le=1.0)
    current_solution: str = "nothing in particular"
    pain_points: list[str] = Field(default_factory=list)
    objection_style: Literal[
        "skeptic", "pragmatist", "enthusiast", "bargain-hunter", "loyalist"
    ] = "pragmatist"
    purchase_history_sketch: str = ""

    # Layer 4 — media & social behavior
    channels: dict[str, float] = Field(default_factory=dict)
    influence: float = Field(0.5, ge=0.0, le=1.0)
    susceptibility: float = Field(0.5, ge=0.0, le=1.0)
    trust_in_ads: float = Field(0.3, ge=0.0, le=1.0)

    # Layer 5 — narrative card (what the LLM reads)
    persona_card: str = ""

    # Assigned after clustering; -1 = unassigned.
    archetype: int = -1

    def channel_propensity(self, channel: str, default: float = 0.5) -> float:
        v = self.channels.get(channel, default)
        return min(1.0, max(0.0, float(v)))

    def feature_vector(self) -> list[float]:
        """Numeric embedding of the structured layers, used for archetype
        clustering. Order is stable — do not reorder without re-clustering."""
        p = self.personality
        return [
            self.age / 100.0,
            {"low": 0.0, "mid": 0.5, "high": 1.0}[self.income_bracket],
            p.openness,
            p.conscientiousness,
            p.extraversion,
            p.agreeableness,
            p.neuroticism,
            self.risk_tolerance,
            self.novelty_seeking,
            self.category_involvement,
            self.price_sensitivity,
            self.brand_loyalty,
            self.influence,
            self.susceptibility,
            self.trust_in_ads,
        ]

    def cache_key(self) -> str:
        """Stable hash of everything that shapes this persona's reactions."""
        payload = self.model_dump(exclude={"id", "archetype"})
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class NetworkSpec(BaseModel):
    """Social-graph topology for the audience."""

    topology: Literal["watts-strogatz", "barabasi-albert", "random"] = (
        "watts-strogatz"
    )
    k: int = Field(8, ge=2, le=64, description="mean degree (WS) / 2*m (BA)")
    rewire: float = Field(0.1, ge=0.0, le=1.0, description="WS rewiring prob")
    degree_by_influence: bool = Field(
        True,
        description="assign high-degree positions to high-influence personas",
    )

    @field_validator("k")
    @classmethod
    def _even_k(cls, v: int) -> int:
        # Watts-Strogatz ring lattice needs an even mean degree.
        return v if v % 2 == 0 else v + 1


class ConditionalRule(BaseModel):
    """A small correlation knob: when a sampled field matches, shift another.

    Example: older personas trust email more::

        if_field: age, gte: 45, then_field: channels.email, add: 0.15
    """

    if_field: str
    equals: Any | None = None
    is_in: list[Any] | None = None
    gte: float | None = None
    lte: float | None = None
    then_field: str
    add: float | None = None
    set_value: Any | None = None
    set_dist: dict[str, float] | None = None


class AudienceSpec(BaseModel):
    """Recipe for generating a persona population (the YAML the user writes)."""

    name: str
    description: str = ""
    product_context: str = Field(
        "",
        description="what product/category this audience is shopping for — "
        "grounds every persona card and reaction prompt",
    )
    size: int = Field(100, ge=5, le=5000)
    seed: int = 42
    distributions: dict[str, Any] = Field(
        default_factory=dict,
        description="field -> categorical {value: weight} or numeric "
        "{mean, sd, min?, max?}",
    )
    conditionals: list[ConditionalRule] = Field(default_factory=list)
    network: NetworkSpec = Field(default_factory=NetworkSpec)
    n_archetypes: int = Field(
        0, ge=0, le=200, description="0 = auto (~size/12, clamped to 4..80)"
    )

    @field_validator("name")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("audience name cannot be empty")
        bad = set('<>:"/\\|?*')
        if any(c in bad for c in v):
            raise ValueError(f"audience name contains filesystem-unsafe chars: {v!r}")
        return v


class Audience(BaseModel):
    """A generated population: the spec that produced it plus the personas."""

    spec: AudienceSpec
    personas: list[Persona]
    # persona index -> list of neighbor persona indices (undirected edges
    # stored both ways). Kept here so NetLogo and PythonWorld build the SAME
    # graph and replicate runs are paired.
    edges: list[list[int]] = Field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.personas)

    def archetype_members(self) -> dict[int, list[int]]:
        out: dict[int, list[int]] = {}
        for i, p in enumerate(self.personas):
            out.setdefault(p.archetype, []).append(i)
        return out


# ── Stimulus ─────────────────────────────────────────────────────────────────


class ChannelParams(BaseModel):
    """How a stimulus is delivered into the simulated world."""

    channel: Literal["email", "paid_social", "organic"] = "email"
    send_tick: int = Field(1, ge=1, description="tick the campaign launches")
    # email: fraction of the audience on the list. paid_social: fraction
    # reachable by targeting.
    reach: float = Field(1.0, ge=0.0, le=1.0)
    # paid_social: impressions per tick as a fraction of reachable audience
    # (budget proxy). email delivers everything at send_tick.
    impressions_per_tick: float = Field(0.15, ge=0.0, le=1.0)
    frequency_cap: int = Field(3, ge=1, le=20)


class Stimulus(BaseModel):
    """One campaign artifact, normalized so every channel reads the same way."""

    id: str
    variant_of: str | None = Field(
        None, description="id of the base variant this is an A/B alternative to"
    )
    type: Literal["email", "social_ad", "landing_page", "search_ad"] = "email"

    # Pre-click surface — ALL the stage-1 attention gate sees.
    teaser: dict[str, str] = Field(
        default_factory=dict,
        description="email: subject/sender/preheader; ad: headline/thumbnail",
    )

    # Full content — stage 2 material.
    body_text: str = ""
    cta: str = ""
    offer: str | None = None
    price_shown: str | None = None
    visual_description: str | None = None

    channel_params: ChannelParams = Field(default_factory=ChannelParams)

    def cache_key(self) -> str:
        payload = self.model_dump(exclude={"channel_params"})
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def teaser_text(self) -> str:
        return "\n".join(f"{k}: {v}" for k, v in self.teaser.items() if v)


class CampaignSpec(BaseModel):
    """A campaign = one audience x one or more stimulus variants."""

    name: str
    audience: str = Field(description="name of a saved audience")
    stimuli: list[Stimulus]
    replicates: int = Field(3, ge=1, le=30)
    max_ticks: int = Field(72, ge=1, le=2000, description="1 tick = 1 sim hour")
    fidelity: Literal["fast", "mixed", "full"] = "mixed"
    # `mixed` mode: this many personas get individual LLM calls; the rest
    # sample from their archetype's response distribution.
    full_fidelity_sample: int = Field(150, ge=10, le=2000)
    seed: int = 42

    @field_validator("stimuli")
    @classmethod
    def _unique_ids(cls, v: list[Stimulus]) -> list[Stimulus]:
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("stimulus ids must be unique within a campaign")
        if not ids:
            raise ValueError("campaign needs at least one stimulus")
        return v

    @field_validator("name")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("campaign name cannot be empty")
        bad = set('<>:"/\\|?*')
        if any(c in bad for c in v):
            raise ValueError(f"campaign name contains filesystem-unsafe chars: {v!r}")
        return v


# ── Cognition ────────────────────────────────────────────────────────────────


class ExposureEvent(BaseModel):
    """One pending 'a persona encounters the stimulus' moment, read from the
    world each tick."""

    agent_index: int = Field(description="persona index == NetLogo `who`")
    exposure_type: Literal["direct", "social"] = "direct"
    source_index: int | None = Field(
        None, description="neighbor who shared it (social exposures)"
    )
    source_comment: str = Field(
        "", description="the sharer's verbatim reason, shown to the receiver"
    )
    prior_sentiment: float = Field(0.0, ge=-1.0, le=1.0)
    exposure_count: int = Field(1, ge=1)
    tick: int = 0


class Stage1Decision(BaseModel):
    """Attention-gate outcome: did the teaser earn a look at all?"""

    action: Stage1Action
    reason: str = Field("", max_length=400)


class Reaction(BaseModel):
    """Full stage-2 reaction to the stimulus content (LLM structured output)."""

    attention_seconds: int = Field(ge=0, le=300)
    action: ReactionAction
    sentiment: float = Field(ge=-1.0, le=1.0)
    trust_delta: float = Field(0.0, ge=-1.0, le=1.0)
    reason: str = Field("", max_length=600)
    objections: list[str] = Field(default_factory=list)
    would_share_with: Literal["nobody", "close_friends", "publicly"] = "nobody"


class Decision(BaseModel):
    """Resolved outcome of one exposure event — the record that goes to the
    store, and (numeric/categorical fields only) back into the world."""

    agent_index: int
    persona_id: str
    stimulus_id: str
    tick: int
    exposure_type: str
    stage1: Stage1Decision
    reaction: Reaction | None = None  # None when the gate said no
    state: str  # FunnelState after this event
    will_share: bool = False
    cached: bool = False  # served from archetype/exact cache
    llm_calls: int = 0

    @property
    def sentiment(self) -> float:
        return self.reaction.sentiment if self.reaction else -0.1

    @property
    def verbatim(self) -> str:
        if self.reaction and self.reaction.reason:
            return self.reaction.reason
        return self.stage1.reason


def resolve_state(stage1: Stage1Decision, reaction: Reaction | None) -> str:
    """Map the two cognition stages to a funnel state."""
    if stage1.action != "open":
        return "ignored"
    if reaction is None:
        return "engaged"
    return ACTION_TO_STATE[reaction.action]
