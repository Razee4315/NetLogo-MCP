# SynthAudience — Design Notes

Full plan and rationale: [`plan.md`](../../plan.md) at the repo root.
This file is the shorter engineering reference for the shipped code.

## Architecture (as built)

```
MCP client  ──►  netlogo-mcp server (one process)
                   │
                   ├─ market/tools.py        MCP surface (10 tools)
                   ├─ market/orchestrator.py tick loop
                   │     step ► pending_exposures ► decide_batch ► apply ► log
                   ├─ market/cognition.py    LLMBackend | HeuristicBackend
                   │     + ResponseCache (SQLite) + archetype distributions
                   ├─ market/worlds.py       NetLogoWorld | PythonWorld
                   │     (identical rule semantics — see contract in worlds.py)
                   ├─ market/netlogo_gen.py  market_sim model source
                   └─ market/store.py        runs/decisions/tick_metrics (SQLite)
```

## Key decisions

1. **Hybrid cognition.** The LLM is consulted only at exposure events
   (first contact, first social re-exposure). Diffusion, fatigue, and
   sentiment drift are classical ABM rules. This is what makes 1,000 agents
   affordable.
2. **Two-stage gate.** Stage 1 sees only the teaser (subject/thumbnail) and
   kills most reactions — structurally suppressing LLM positivity bias.
3. **Batched JVM contract.** One `report` reads all pending exposures, one
   `command` writes all decisions. Two JVM hops per tick regardless of
   population size (the workspace lock makes per-agent calls unaffordable).
4. **Paired A/B design.** Replicate r uses the same world seed for every
   variant; variants face identical audiences and reach dice.
5. **No LLM text in NetLogo.** Only validated Pydantic fields (Literal
   states, clamped floats) cross into NetLogo commands. Verbatims live in
   the SQLite event store.
6. **PythonWorld = reference implementation.** Same rules as the NetLogo
   model, pure Python — used by tests/CI/validation; NetLogo is the demo
   and inspection surface. Any rule change must land in both + netlogo_gen.

## Cognition fidelity modes

| mode | LLM calls (1,000 agents, 1 variant) | use |
| --- | --- | --- |
| `full` | ~1,300 | final runs, per-persona verbatims |
| `mixed` | ~150 individual + ~K x draws archetype | default |
| `fast` | ~K x 5 draws (K archetypes ≈ 30-80) | iteration loops |

Exact-repeat caching makes re-running a tweaked campaign nearly free —
only changed exposures are recomputed.

## Environment variables

See `market/config.py` docstring: `SYNTH_DATA_DIR`, `SYNTH_LLM_MODE`
(`mock`/`live`), `SYNTH_LLM_BASE_URL`, `SYNTH_LLM_MODEL`,
`SYNTH_LLM_API_KEY`, `SYNTH_LLM_CONCURRENCY`, `SYNTH_LLM_TIMEOUT`,
`SYNTH_LLM_TEMPERATURE`.

## Validation status

- Rung 1 (Bass diffusion S-curve): **PASS** (R² = 0.998) —
  `validation/bass_diffusion.py`
- Rung 2 (Hillstrom backtest): infrastructure runs end-to-end;
  heuristic baseline scores Spearman rho ≈ -0.08 on segment ranking
  (i.e. the rule-based baseline FAILS — that is the gap LLM cognition
  must close). `validation/hillstrom/backtest.py`
- Rung 3 (robustness audit): not started — needs a live LLM.
