"""Archetype clustering tests."""

from __future__ import annotations

from netlogo_mcp.market.archetypes import (
    archetype_summary,
    assign_archetypes,
    auto_k,
    representative_indices,
)
from netlogo_mcp.market.personas import generate_audience
from netlogo_mcp.market.schemas import AudienceSpec


def test_auto_k_clamps():
    assert auto_k(10) == 4
    assert auto_k(240) == 20
    assert auto_k(5000) == 80


def test_assign_archetypes_deterministic(small_spec):
    a1 = assign_archetypes(generate_audience(small_spec))
    a2 = assign_archetypes(generate_audience(small_spec))
    assert [p.archetype for p in a1.personas] == [p.archetype for p in a2.personas]


def test_every_persona_gets_an_archetype(small_spec):
    aud = assign_archetypes(generate_audience(small_spec))
    assert all(p.archetype >= 0 for p in aud.personas)
    k = len({p.archetype for p in aud.personas})
    assert 2 <= k <= aud.size


def test_summary_shape(small_spec):
    aud = assign_archetypes(generate_audience(small_spec))
    summary = archetype_summary(aud)
    assert sum(s["size"] for s in summary) == aud.size
    for s in summary:
        assert s["label"]
        assert isinstance(s["distinctive"], list)


def test_representative_indices_stratified():
    spec = AudienceSpec(name="strat", size=200, seed=3)
    aud = assign_archetypes(generate_audience(spec))
    picked = representative_indices(aud, 50, seed=1)
    assert len(picked) == 50
    assert len(set(picked)) == 50
    # Every archetype with >= 200/50 members should be represented.
    picked_archetypes = {aud.personas[i].archetype for i in picked}
    big = {a for a, m in aud.archetype_members().items() if len(m) >= 8}
    assert big <= picked_archetypes
