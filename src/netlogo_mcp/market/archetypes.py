"""Archetype clustering — the scale unlock for LLM cost.

Personas are clustered on their structured feature vectors (k-means). In
``fast``/``mixed`` fidelity the cognition engine calls the LLM once per
(archetype x stimulus x exposure-type) and lets individual agents *sample*
from their archetype's response distribution, so a 1,000-agent run costs
~K x variants LLM calls instead of 1,000+.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from .schemas import Audience, Persona

# Names for feature_vector() positions — keep in sync with
# Persona.feature_vector().
FEATURE_NAMES: tuple[str, ...] = (
    "age",
    "income",
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
    "risk_tolerance",
    "novelty_seeking",
    "category_involvement",
    "price_sensitivity",
    "brand_loyalty",
    "influence",
    "susceptibility",
    "trust_in_ads",
)


def auto_k(size: int) -> int:
    """Default archetype count: ~1 per 12 personas, clamped to [4, 80]."""
    return int(min(80, max(4, round(size / 12))))


def assign_archetypes(audience: Audience, n_archetypes: int = 0) -> Audience:
    """Cluster personas and set ``persona.archetype`` in place. Deterministic
    given the audience spec's seed."""
    k = n_archetypes or audience.spec.n_archetypes or auto_k(audience.size)
    k = min(k, audience.size)

    X = np.array([p.feature_vector() for p in audience.personas], dtype=float)
    # Standardize so age doesn't dominate the unit-interval traits.
    mu, sigma = X.mean(axis=0), X.std(axis=0)
    sigma[sigma == 0] = 1.0
    Xs = (X - mu) / sigma

    from sklearn.cluster import KMeans

    km = KMeans(n_clusters=k, n_init=10, random_state=audience.spec.seed)
    labels = km.fit_predict(Xs)
    for p, label in zip(audience.personas, labels, strict=False):
        p.archetype = int(label)
    return audience


def _dominant(values: list[str]) -> str:
    if not values:
        return "-"
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=lambda kk: counts[kk])


def archetype_label(members: list[Persona]) -> str:
    """Short human-readable handle, e.g. 'skeptic - mid income - 40s'."""
    style = _dominant([p.objection_style for p in members])
    income = _dominant([p.income_bracket for p in members])
    mean_age = int(np.mean([p.age for p in members]))
    return f"{style} · {income} income · {mean_age // 10 * 10}s"


def archetype_summary(audience: Audience) -> list[dict[str, Any]]:
    """Per-archetype description: size, label, and most-deviating traits."""
    X = np.array([p.feature_vector() for p in audience.personas], dtype=float)
    pop_mean = X.mean(axis=0)
    pop_std = X.std(axis=0)
    pop_std[pop_std == 0] = 1.0

    out: list[dict[str, Any]] = []
    for arch, idxs in sorted(audience.archetype_members().items()):
        if arch < 0:
            continue
        members = [audience.personas[i] for i in idxs]
        centroid = X[idxs].mean(axis=0)
        z = (centroid - pop_mean) / pop_std
        top = np.argsort(-np.abs(z))[:3]
        traits = [
            f"{FEATURE_NAMES[t]} {'high' if z[t] > 0 else 'low'} ({z[t]:+.1f}σ)"
            for t in top
            if abs(z[t]) > 0.25
        ]
        out.append(
            {
                "archetype": arch,
                "label": archetype_label(members),
                "size": len(members),
                "distinctive": traits,
                "representative": members[0].id,
            }
        )
    return out


def representative_indices(
    audience: Audience, sample_size: int, seed: int = 0
) -> list[int]:
    """Stratified sample across archetypes for `mixed` fidelity: pick
    proportionally from each archetype (at least 1 each) up to sample_size."""
    rng = np.random.default_rng(seed)
    groups = {a: idxs for a, idxs in audience.archetype_members().items() if a >= 0}
    if not groups:
        n = min(sample_size, audience.size)
        return list(rng.choice(audience.size, size=n, replace=False))

    total = audience.size
    picked: list[int] = []
    for _, idxs in sorted(groups.items()):
        quota = max(1, round(sample_size * len(idxs) / total))
        quota = min(quota, len(idxs))
        picked.extend(
            int(i) for i in rng.choice(idxs, size=quota, replace=False)
        )
    # Rounding can over- or undershoot the target: trim randomly, then top up
    # from personas not yet picked.
    rng.shuffle(picked)
    picked = picked[:sample_size]
    if len(picked) < sample_size:
        remaining = [i for i in range(total) if i not in set(picked)]
        need = min(sample_size - len(picked), len(remaining))
        picked.extend(
            int(i) for i in rng.choice(remaining, size=need, replace=False)
        )
    return sorted(picked)
