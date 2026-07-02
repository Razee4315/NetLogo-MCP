"""Persona Engine tests: determinism, distribution conformance, network shape."""

from __future__ import annotations

import numpy as np

from netlogo_mcp.market.personas import (
    generate_audience,
    list_audiences,
    load_audience,
    load_spec,
    save_audience,
)
from netlogo_mcp.market.schemas import AudienceSpec, ConditionalRule, NetworkSpec


def test_generation_is_deterministic(small_spec):
    a1 = generate_audience(small_spec)
    a2 = generate_audience(small_spec)
    assert [p.model_dump() for p in a1.personas] == [
        p.model_dump() for p in a2.personas
    ]
    assert a1.edges == a2.edges


def test_different_seed_different_population(small_spec):
    a1 = generate_audience(small_spec)
    a2 = generate_audience(small_spec.model_copy(update={"seed": 99}))
    assert [p.age for p in a1.personas] != [p.age for p in a2.personas]


def test_population_size_and_ids(small_spec):
    aud = generate_audience(small_spec)
    assert aud.size == small_spec.size
    assert len({p.id for p in aud.personas}) == small_spec.size


def test_categorical_distribution_conformance():
    spec = AudienceSpec(
        name="dist-check",
        size=600,
        seed=1,
        distributions={"income_bracket": {"low": 0.8, "mid": 0.1, "high": 0.1}},
    )
    aud = generate_audience(spec)
    low_share = sum(p.income_bracket == "low" for p in aud.personas) / aud.size
    assert 0.72 <= low_share <= 0.88


def test_numeric_distribution_conformance():
    spec = AudienceSpec(
        name="num-check",
        size=600,
        seed=2,
        distributions={"trust_in_ads": {"mean": 0.7, "sd": 0.05}},
    )
    aud = generate_audience(spec)
    mean_trust = np.mean([p.trust_in_ads for p in aud.personas])
    assert 0.65 <= mean_trust <= 0.75


def test_numeric_bounds_respected():
    spec = AudienceSpec(
        name="bounds",
        size=200,
        seed=3,
        distributions={"age": {"mean": 20, "sd": 15, "min": 18, "max": 30}},
    )
    aud = generate_audience(spec)
    assert all(18 <= p.age <= 30 for p in aud.personas)


def test_conditional_rule_shifts_field():
    spec = AudienceSpec(
        name="cond",
        size=300,
        seed=4,
        distributions={"age": {"mean": 50, "sd": 3, "min": 45, "max": 60}},
        conditionals=[
            ConditionalRule(
                if_field="age", gte=45, then_field="channels.email", add=0.4
            )
        ],
    )
    aud = generate_audience(spec)
    mean_email = np.mean([p.channels["email"] for p in aud.personas])
    assert mean_email > 0.7  # default mean 0.45 + 0.4 shift, clipped at 1


def test_persona_cards_nonempty_and_varied(small_spec):
    aud = generate_audience(small_spec)
    cards = [p.persona_card for p in aud.personas]
    assert all(len(c) > 80 for c in cards)
    assert len(set(cards)) > small_spec.size * 0.9  # near-unique
    assert any(small_spec.product_context.split()[1] in c for c in cards)


def test_network_edges_symmetric_and_connected_enough(small_spec):
    aud = generate_audience(small_spec)
    adj = aud.edges
    assert len(adj) == aud.size
    for i, nbrs in enumerate(adj):
        for j in nbrs:
            assert i in adj[j]
            assert i != j
    degrees = [len(n) for n in adj]
    assert np.mean(degrees) >= small_spec.network.k * 0.8
    assert min(degrees) >= 1


def test_barabasi_albert_gives_hubs_to_influencers():
    spec = AudienceSpec(
        name="ba",
        size=120,
        seed=5,
        network=NetworkSpec(topology="barabasi-albert", k=4),
    )
    aud = generate_audience(spec)
    degrees = np.array([len(n) for n in aud.edges])
    influence = np.array([p.influence for p in aud.personas])
    # Hubs should be the high-influence personas (positive rank correlation).
    corr = np.corrcoef(degrees, influence)[0, 1]
    assert corr > 0.5
    assert degrees.max() >= degrees.mean() * 2  # heavy tail exists


def test_ws_relabel_preserves_structure():
    spec = AudienceSpec(name="ws", size=60, seed=6)
    aud = generate_audience(spec)
    n_edges = sum(len(n) for n in aud.edges) // 2
    expected = 60 * spec.network.k // 2
    assert abs(n_edges - expected) <= expected * 0.15


def test_save_load_roundtrip(small_spec):
    aud = generate_audience(small_spec)
    save_audience(aud)
    loaded = load_audience(small_spec.name)
    assert loaded.spec.name == small_spec.name
    assert loaded.size == aud.size
    assert loaded.edges == aud.edges
    listing = list_audiences()
    assert any(a["name"] == small_spec.name for a in listing)


def test_load_spec_from_yaml_text():
    spec = load_spec(
        """
name: yaml-audience
product_context: a budgeting app
size: 25
seed: 9
distributions:
  income_bracket: {low: 0.5, mid: 0.4, high: 0.1}
network:
  topology: watts-strogatz
  k: 6
"""
    )
    assert spec.name == "yaml-audience"
    assert spec.size == 25
    assert spec.network.k == 6
    aud = generate_audience(spec)
    assert aud.size == 25
