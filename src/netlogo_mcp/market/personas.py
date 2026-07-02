"""Persona Engine — generate a population from an audience spec.

Everything is seeded and deterministic: the same ``AudienceSpec`` always
produces the identical population and social graph, so campaign variants can
be compared against a *frozen* audience (paired A/B design).

Distribution spec format (per field, in ``AudienceSpec.distributions``):

- categorical: ``{"low": 0.3, "mid": 0.5, "high": 0.2}`` (weights, normalized)
- numeric: ``{"mean": 38, "sd": 12, "min": 18, "max": 75}``
- list fields (``values``, ``pain_points``): categorical weights; ``k`` picks
  per persona may be given as ``{"__k__": 3, "frugality": 0.4, ...}``

Field paths may be nested with dots: ``personality.openness``,
``channels.email``.
"""

from __future__ import annotations

import json
import re
from typing import Any

import numpy as np
import yaml

from .config import get_audiences_dir
from .schemas import Audience, AudienceSpec, NetworkSpec, Persona

# ── Default distributions (generic adult consumer population) ────────────────

_LIST_FIELDS = {"values", "pain_points"}

DEFAULT_DISTRIBUTIONS: dict[str, Any] = {
    "age": {"mean": 38, "sd": 13, "min": 18, "max": 75},
    "gender": {"female": 0.49, "male": 0.49, "nonbinary": 0.02},
    "location": {"urban": 0.55, "suburban": 0.30, "rural": 0.15},
    "income_bracket": {"low": 0.30, "mid": 0.50, "high": 0.20},
    "education": {
        "high school": 0.30,
        "bachelor's degree": 0.40,
        "graduate degree": 0.20,
        "trade / self-taught": 0.10,
    },
    "occupation": {
        "office professional": 0.25,
        "service worker": 0.15,
        "healthcare worker": 0.08,
        "teacher": 0.07,
        "engineer / developer": 0.10,
        "small business owner": 0.08,
        "sales / marketing": 0.08,
        "skilled trades": 0.08,
        "student": 0.06,
        "retired": 0.05,
    },
    "household": {
        "living alone": 0.28,
        "couple, no kids": 0.28,
        "family with kids": 0.32,
        "shared household": 0.12,
    },
    "personality.openness": {"mean": 0.5, "sd": 0.15},
    "personality.conscientiousness": {"mean": 0.5, "sd": 0.15},
    "personality.extraversion": {"mean": 0.5, "sd": 0.15},
    "personality.agreeableness": {"mean": 0.5, "sd": 0.15},
    "personality.neuroticism": {"mean": 0.5, "sd": 0.15},
    "risk_tolerance": {"mean": 0.5, "sd": 0.2},
    "novelty_seeking": {"mean": 0.5, "sd": 0.2},
    "category_involvement": {"mean": 0.5, "sd": 0.2},
    "price_sensitivity": {"mean": 0.55, "sd": 0.2},
    "brand_loyalty": {"mean": 0.45, "sd": 0.2},
    "trust_in_ads": {"mean": 0.30, "sd": 0.15},
    "influence": {"mean": 0.35, "sd": 0.2},
    "susceptibility": {"mean": 0.5, "sd": 0.18},
    "channels.email": {"mean": 0.45, "sd": 0.2},
    "channels.paid_social": {"mean": 0.5, "sd": 0.2},
    "channels.organic": {"mean": 0.5, "sd": 0.15},
    "objection_style": {
        "skeptic": 0.25,
        "pragmatist": 0.35,
        "enthusiast": 0.15,
        "bargain-hunter": 0.15,
        "loyalist": 0.10,
    },
    "current_solution": {
        "nothing in particular": 0.35,
        "a competitor's product": 0.30,
        "a DIY workaround": 0.20,
        "an older version of something similar": 0.15,
    },
    "values": {
        "__k__": 3,
        "frugality": 0.35,
        "quality": 0.35,
        "convenience": 0.30,
        "status": 0.15,
        "sustainability": 0.20,
        "novelty": 0.15,
        "community": 0.20,
        "security": 0.25,
        "health": 0.25,
        "family": 0.30,
    },
    "pain_points": {
        "__k__": 2,
        "not enough time": 0.35,
        "existing options feel overpriced": 0.30,
        "overwhelmed by too many choices": 0.25,
        "burned by products that overpromised": 0.30,
        "hard to tell marketing claims apart": 0.25,
        "current solution is clunky but familiar": 0.25,
    },
}


# ── Sampling machinery ───────────────────────────────────────────────────────


def _is_numeric_spec(spec: Any) -> bool:
    return isinstance(spec, dict) and "mean" in spec


def _sample_numeric(spec: dict[str, Any], rng: np.random.Generator) -> float:
    v = float(rng.normal(float(spec["mean"]), float(spec.get("sd", 0.1))))
    lo = float(spec.get("min", 0.0))
    hi = float(spec.get("max", 1.0))
    return float(min(hi, max(lo, v)))


def _sample_categorical(spec: dict[str, Any], rng: np.random.Generator) -> Any:
    items = [(k, float(w)) for k, w in spec.items() if k != "__k__"]
    if not items:
        raise ValueError("empty categorical distribution")
    keys = [k for k, _ in items]
    weights = np.array([max(0.0, w) for _, w in items], dtype=float)
    if weights.sum() <= 0:
        raise ValueError(f"categorical weights sum to zero: {spec!r}")
    return keys[int(rng.choice(len(keys), p=weights / weights.sum()))]


def _sample_list(spec: dict[str, Any], rng: np.random.Generator) -> list[str]:
    k = int(spec.get("__k__", 2))
    items = [(str(key), float(w)) for key, w in spec.items() if key != "__k__"]
    keys = [key for key, _ in items]
    weights = np.array([max(0.0, w) for _, w in items], dtype=float)
    if weights.sum() <= 0 or not keys:
        return []
    k = min(k, len(keys))
    idx = rng.choice(len(keys), size=k, replace=False, p=weights / weights.sum())
    return [keys[int(i)] for i in idx]


def _set_path(obj: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = obj
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _get_path(obj: dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _matches(rule_value: Any, rule: Any) -> bool:
    """Evaluate one ConditionalRule condition against a sampled value."""
    if rule.equals is not None:
        return rule_value == rule.equals
    if rule.is_in is not None:
        return rule_value in rule.is_in
    ok = True
    if rule.gte is not None:
        try:
            ok = ok and float(rule_value) >= rule.gte
        except (TypeError, ValueError):
            return False
    if rule.lte is not None:
        try:
            ok = ok and float(rule_value) <= rule.lte
        except (TypeError, ValueError):
            return False
    return ok


def _apply_conditionals(
    fields: dict[str, Any], spec: AudienceSpec, rng: np.random.Generator
) -> None:
    for rule in spec.conditionals:
        current = _get_path(fields, rule.if_field)
        if current is None or not _matches(current, rule):
            continue
        if rule.set_value is not None:
            _set_path(fields, rule.then_field, rule.set_value)
        elif rule.set_dist is not None:
            _set_path(fields, rule.then_field, _sample_categorical(rule.set_dist, rng))
        elif rule.add is not None:
            old = _get_path(fields, rule.then_field)
            try:
                new = float(old) + rule.add
            except (TypeError, ValueError):
                continue
            # Age is the only unbounded-ish numeric; everything else is [0,1].
            if rule.then_field != "age":
                new = min(1.0, max(0.0, new))
            _set_path(fields, rule.then_field, new)


def _sample_fields(spec: AudienceSpec, rng: np.random.Generator) -> dict[str, Any]:
    dists = {**DEFAULT_DISTRIBUTIONS, **(spec.distributions or {})}
    fields: dict[str, Any] = {}
    for path, dist in dists.items():
        root = path.split(".")[0]
        if root in _LIST_FIELDS:
            value: Any = _sample_list(dist, rng)
        elif _is_numeric_spec(dist):
            value = _sample_numeric(dist, rng)
        else:
            value = _sample_categorical(dist, rng)
        _set_path(fields, path, value)
    if "age" in fields:
        fields["age"] = int(round(float(fields["age"])))
    _apply_conditionals(fields, spec, rng)
    return fields


# ── Persona card (template-based; LLM polish is optional, later) ────────────


def _pick(rng: np.random.Generator, options: list[str]) -> str:
    return options[int(rng.integers(0, len(options)))]


def render_persona_card(
    fields: dict[str, Any], product_context: str, rng: np.random.Generator
) -> str:
    """Deterministic first-person bio (~120-180 words) built from the
    structured layers. Varied phrasing keyed on the seeded RNG so cards don't
    all read identically."""
    age = fields.get("age", 35)
    occ = fields.get("occupation", "worker")
    loc = fields.get("location", "town")
    household = fields.get("household", "")
    income = fields.get("income_bracket", "mid")
    values = fields.get("values", []) or ["getting good value"]
    pains = fields.get("pain_points", []) or []
    style = fields.get("objection_style", "pragmatist")
    current = fields.get("current_solution", "nothing in particular")
    trust = float(fields.get("trust_in_ads", 0.3))
    price_sens = float(fields.get("price_sensitivity", 0.5))
    novelty = float(fields.get("novelty_seeking", 0.5))

    opener = _pick(
        rng,
        [
            f"I'm {age}, working as a {occ} in a {loc} area.",
            f"{age} years old, {occ}, living {loc}-side.",
            f"I'm a {age}-year-old {occ} based in a {loc} neighborhood.",
        ],
    )
    home = f" At home it's {household}." if household else ""

    money = {
        "low": _pick(
            rng,
            [
                "Money is tight, so every purchase has to justify itself.",
                "I budget carefully — impulse buys are rare for me.",
            ],
        ),
        "mid": _pick(
            rng,
            [
                "I'm comfortable but not careless with money.",
                "I can afford the occasional extra, but I compare before I buy.",
            ],
        ),
        "high": _pick(
            rng,
            [
                "Price matters less to me than quality and time saved.",
                "I'll pay a premium when something clearly works better.",
            ],
        ),
    }[income]

    cares = "What I care about most: " + ", ".join(values[:3]) + "."
    pain_txt = (
        (" Lately, " + "; ".join(pains[:2]) + " — that's what wears on me.")
        if pains
        else ""
    )

    style_txt = {
        "skeptic": "I assume marketing is exaggerating until proven otherwise.",
        "pragmatist": "I don't care about hype — show me it solves my problem.",
        "enthusiast": "I genuinely enjoy discovering new products worth talking about.",
        "bargain-hunter": "I rarely pay full price; a real deal gets my attention fast.",
        "loyalist": "Once something works for me I stick with it, so switching is a big ask.",
    }[style]

    ad_txt = (
        "Ads mostly wash over me — I've learned to tune them out."
        if trust < 0.35
        else (
            "I'll give an ad a chance if it speaks to something I actually need."
            if trust < 0.65
            else "I discover a fair number of things through ads and don't mind that."
        )
    )

    if price_sens > 0.65:
        ad_txt += " If there's no clear price, I get suspicious."
    if novelty > 0.65:
        ad_txt += " New things do catch my eye, I'll admit."

    ctx = (
        f" Right now, regarding {product_context}: I'm using {current}."
        if product_context
        else f" For most things in this space I currently rely on {current}."
    )

    return f"{opener}{home} {money} {cares}{pain_txt} {style_txt} {ad_txt}{ctx}"


def _purchase_history_sketch(
    fields: dict[str, Any], rng: np.random.Generator
) -> str:
    loyalty = float(fields.get("brand_loyalty", 0.5))
    price_sens = float(fields.get("price_sensitivity", 0.5))
    if loyalty > 0.65:
        base = "Buys from the same few brands for years; a bad experience is what it takes to switch."
    elif price_sens > 0.65:
        base = "Shops around every time; has switched providers twice in two years to save money."
    else:
        base = "Mixes habit and comparison: repeat-buys basics, researches anything over an impulse threshold."
    extra = _pick(
        rng,
        [
            " Reads reviews before anything unfamiliar.",
            " Asks a friend's opinion before bigger purchases.",
            " Abandons carts often when shipping or price surprises appear.",
        ],
    )
    return base + extra


# ── Social network generation ────────────────────────────────────────────────


def _ws_edges(n: int, k: int, rewire: float, rng: np.random.Generator) -> set[tuple[int, int]]:
    """Watts-Strogatz small world on n nodes, mean degree k (even)."""
    edges: set[tuple[int, int]] = set()
    half = max(1, k // 2)
    for i in range(n):
        for j in range(1, half + 1):
            a, b = i, (i + j) % n
            edges.add((min(a, b), max(a, b)))
    # Rewire each lattice edge with prob `rewire` (keep one endpoint).
    out: set[tuple[int, int]] = set()
    for a, b in sorted(edges):
        if rng.random() < rewire:
            for _ in range(10):  # retry to avoid self-loops/duplicates
                c = int(rng.integers(0, n))
                e = (min(a, c), max(a, c))
                if c != a and e not in out and e not in edges:
                    out.add(e)
                    break
            else:
                out.add((a, b))
        else:
            out.add((a, b))
    return out


def _ba_edges(n: int, m: int, rng: np.random.Generator) -> set[tuple[int, int]]:
    """Barabási-Albert preferential attachment; early nodes become hubs."""
    m = max(1, min(m, n - 1))
    edges: set[tuple[int, int]] = set()
    targets = list(range(m))
    repeated: list[int] = list(range(m))
    for v in range(m, n):
        chosen: set[int] = set()
        while len(chosen) < m:
            pick = repeated[int(rng.integers(0, len(repeated)))] if repeated else int(
                rng.integers(0, v)
            )
            if pick != v:
                chosen.add(pick)
        for t in chosen:
            edges.add((min(v, t), max(v, t)))
            repeated.extend([v, t])
        targets.append(v)
    return edges


def _random_edges(n: int, k: int, rng: np.random.Generator) -> set[tuple[int, int]]:
    target = n * k // 2
    edges: set[tuple[int, int]] = set()
    while len(edges) < target:
        a, b = int(rng.integers(0, n)), int(rng.integers(0, n))
        if a != b:
            edges.add((min(a, b), max(a, b)))
    return edges


def build_network(
    net: NetworkSpec, personas: list[Persona], rng: np.random.Generator
) -> list[list[int]]:
    """Build the social graph; returns adjacency list indexed by persona.

    When ``degree_by_influence`` is set, graph *slots* are relabeled so that
    high-degree slots go to high-influence personas (hubs = influencers).
    """
    n = len(personas)
    if net.topology == "barabasi-albert":
        edges = _ba_edges(n, max(1, net.k // 2), rng)
    elif net.topology == "random":
        edges = _random_edges(n, net.k, rng)
    else:
        edges = _ws_edges(n, net.k, net.rewire, rng)

    mapping = list(range(n))  # slot -> persona index
    if net.degree_by_influence and n > 1:
        degree = [0] * n
        for a, b in edges:
            degree[a] += 1
            degree[b] += 1
        slots_by_degree = sorted(range(n), key=lambda s: -degree[s])
        personas_by_influence = sorted(range(n), key=lambda i: -personas[i].influence)
        for slot, pi in zip(slots_by_degree, personas_by_influence):
            mapping[slot] = pi

    adj: list[list[int]] = [[] for _ in range(n)]
    for a, b in edges:
        pa, pb = mapping[a], mapping[b]
        if pb not in adj[pa]:
            adj[pa].append(pb)
        if pa not in adj[pb]:
            adj[pb].append(pa)
    for neighbors in adj:
        neighbors.sort()
    return adj


# ── Population generation ────────────────────────────────────────────────────


def generate_audience(spec: AudienceSpec) -> Audience:
    """Sample the full population + social graph from a spec. Deterministic."""
    rng = np.random.default_rng(spec.seed)
    personas: list[Persona] = []
    for i in range(spec.size):
        fields = _sample_fields(spec, rng)
        fields["purchase_history_sketch"] = _purchase_history_sketch(fields, rng)
        fields["persona_card"] = render_persona_card(
            fields, spec.product_context, rng
        )
        personas.append(Persona(id=f"{spec.name}-{i:04d}", **fields))

    edges = build_network(spec.network, personas, rng)
    return Audience(spec=spec, personas=personas, edges=edges)


# ── Spec + audience persistence ──────────────────────────────────────────────


def load_spec(source: str) -> AudienceSpec:
    """Parse an AudienceSpec from YAML text or a path to a YAML file."""
    text = source
    if "\n" not in source and (
        source.endswith((".yaml", ".yml")) or "/" in source or "\\" in source
    ):
        from pathlib import Path

        p = Path(source)
        if not p.is_file():
            raise FileNotFoundError(f"audience spec file not found: {source}")
        text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("audience spec YAML must be a mapping")
    return AudienceSpec(**data)


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()) or "audience"


def save_audience(audience: Audience) -> str:
    path = get_audiences_dir() / f"{_slug(audience.spec.name)}.json"
    path.write_text(audience.model_dump_json(indent=1), encoding="utf-8")
    return str(path)


def load_audience(name: str) -> Audience:
    path = get_audiences_dir() / f"{_slug(name)}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"audience '{name}' not found — expected {path}. "
            "Use generate_audience first."
        )
    return Audience(**json.loads(path.read_text(encoding="utf-8")))


def list_audiences() -> list[dict[str, Any]]:
    out = []
    for p in sorted(get_audiences_dir().glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            spec = data.get("spec", {})
            out.append(
                {
                    "name": spec.get("name", p.stem),
                    "size": len(data.get("personas", [])),
                    "product_context": spec.get("product_context", ""),
                    "file": str(p),
                }
            )
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return out
