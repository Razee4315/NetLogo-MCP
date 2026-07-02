# SynthAudience — Implementation Status

_Everything in [`plan.md`](plan.md) that could be built and tested without a
live LLM is built and tested. This file says exactly what is DONE, what
REMAINS, and how to do each remaining step._

**Snapshot:** 313 tests passing (79 new for the market module), ruff-clean,
NetLogo integration verified against the live NetLogo 7.0.3 workspace,
Bass-diffusion validation passing, Hillstrom backtest running end-to-end on
the real 64k-customer dataset.

---

## ✅ DONE

### Core engine (plan.md §4-§8) — `src/netlogo_mcp/market/`

| module | what it does | tested |
| --- | --- | --- |
| `schemas.py` | Persona (5 layers), AudienceSpec, Stimulus, CampaignSpec, ExposureEvent, Reaction, Decision — all Pydantic, all validated | ✅ |
| `personas.py` | Seeded population sampling (categorical + numeric + list distributions, conditional correlation rules), template-based persona cards, Watts-Strogatz / Barabási-Albert / random networks with influence-ranked hubs, YAML specs, save/load | ✅ 18 tests |
| `archetypes.py` | K-means archetype clustering, auto-K, stratified representative sampling for `mixed` fidelity | ✅ |
| `prompts.py` | Two-stage prompts with all 7 anti-bias measures from plan §5.2 (base-rate anchoring, ignore-default framing, reasons-before-action, persona-conditioned skepticism, ...) | ✅ |
| `cognition.py` | **LLMBackend** (OpenAI-compatible → works with Ollama/llama.cpp/cloud; JSON-schema structured outputs with graceful degradation; tenacity retries; malformed-JSON recovery) + **HeuristicBackend** (deterministic persona-driven rule model = default until LLM installed, test double, and ablation baseline) + SQLite response cache + archetype response distributions + bounded concurrency | ✅ 35 tests incl. fake-server transport tests |
| `stimulus.py` | Email/social-ad builders, HTML ingestion (bs4 + html2text, CTA + price detection), campaign YAML persistence | ✅ |
| `netlogo_gen.py` | Generates the `market_sim` NetLogo model (exposure channels, WOM scheduling, DeGroot drift, funnel coloring, monitors + funnel plot widgets) | ✅ + **live-verified** |
| `worlds.py` | `WorldBridge` contract; **PythonWorld** (pure-Python reference impl, runs in CI) and **NetLogoWorld** (batched: 2 JVM hops/tick regardless of population; LLM text can never reach NetLogo commands) | ✅ 15 tests |
| `orchestrator.py` | Tick loop, paired A/B seeds across variants, verbatim propagation into social exposures, event-store logging, watch mode | ✅ e2e tests |
| `store.py` | SQLite event store (runs / decisions / tick_metrics), parquet/CSV export | ✅ |
| `calibration.py` | Logit-linear per-channel/per-stage maps, benchmark base rates (`data/market/base_rates.json`), fit-from-real-campaign-CSV | ✅ |
| `analytics.py` | Funnel with 95% CIs across replicates, segment breakdown, objection mining (TF-IDF + k-means, offline), paired variant comparison (two-proportion z-test), WOM amplification, weak-point diagnosis | ✅ |
| `report.py` | Pre-flight report: markdown + standalone HTML with plotly funnel/segment charts; honest disclaimers (heuristic mode, uncalibrated absolutes) | ✅ |

### MCP tools (plan.md §11) — registered on the existing server

`generate_audience`, `list_audiences`, `get_audience`, `create_campaign`,
`list_campaigns`, `run_campaign` (engine=netlogo|python, watch mode),
`get_campaign_report`, `compare_campaign_variants`, `interview_persona`
(focus-group), `calibrate`, `market_info`. Full conversational flow covered
by `tests/market/test_market_tools.py`.

### Live NetLogo verification (done in this session, real JVM)

The generated model was loaded into NetLogo 7.0.3 and the exact
`NetLogoWorld` command sequence exercised: setup + campaign config, email
delivery, decision write-back, word-of-mouth propagation (neighbors of the
sharer received social exposures with the correct source), `state-counts`,
`quiet?`. Two real bugs were found and fixed this way:
1. `clear-all` wipes campaign globals → params now set via
   `configure-campaign` *after* `setup-world`.
2. pynetlogo cannot marshal booleans in nested lists → `pending-exposures`
   now numeric-only.

### Validation (plan.md §10)

- **Rung 1 — Bass diffusion: PASS.** `validation/bass_diffusion.py`:
  logistic fit R² = 0.998, 299/300 reached from a 5% seed, WOM dominated
  1261:17. The diffusion machinery produces textbook S-curves.
- **Rung 2 — Hillstrom backtest: infrastructure DONE.**
  `validation/hillstrom/` — real dataset downloaded (64k customers),
  covariate→persona mapping implemented, segment-ranking scored with
  Spearman rho. **Heuristic baseline: rho ≈ -0.08 (FAILS)** — recorded
  deliberately: this is the rule-based baseline the LLM must beat, exactly
  the ablation the paper needs.
- **Phase-0 spike: PASS** on diversity criteria (heuristic mode).
  `validation/spike/spike.py` — rerun with the live LLM (see below).

### Extras

- `dashboard/app.py` — Streamlit results browser (funnel, A/B, segments,
  objections, timeline, decision log with CSV export).
- Example specs: `src/netlogo_mcp/data/market/audience_examples/`
  (saas-founders, busy-parents, an A/B email campaign).
- Docs: `docs/market/design.md` (engineering reference),
  `docs/market/model-bakeoff.md` (protocol + scorecard to fill in).
- `.gitignore` covers `market_data/` and generated model files.

---

## ⏳ REMAINING (and exactly how to do each)

### 1. Wire up the local LLM ← **the one you're doing next**

Everything is coded and transport-tested against a fake server; it only
needs a live endpoint. When your model is downloaded:

```powershell
# one-time
ollama pull qwen3:4b            # or your chosen model
$env:OLLAMA_NUM_PARALLEL = "8"  # match SYNTH_LLM_CONCURRENCY

# per session (or put in .env)
$env:SYNTH_LLM_MODE = "live"
$env:SYNTH_LLM_MODEL = "qwen3:4b"
# defaults already point at http://localhost:11434/v1

# smoke test (2 minutes)
uv run python validation/spike/spike.py
```

PASS criteria printed by the script: ≥3 distinct decision paths, non-homo-
geneous gate, JSON compliance (watch for retry warnings), calls/sec. Then
run the busy-parents example campaign end-to-end via MCP
(`run_campaign`, engine `python` first, then `netlogo` to watch it live).

**Tell me when Ollama is set up and I'll run the whole live-LLM test pass
and the model bake-off with you.**

### 2. Model bake-off (30-60 min, needs #1)

Follow `docs/market/model-bakeoff.md` — spike script per candidate model,
fill the scorecard, set the winner as the `SYNTH_LLM_MODEL` default.

### 3. Hillstrom backtest with LLM cognition (needs #1)

```powershell
$env:SYNTH_LLM_MODE = "live"
uv run python validation/hillstrom/backtest.py
```

Target: segment-ranking Spearman rho > 0.4 (heuristic baseline: -0.08).
If it fails: iterate on the covariate→persona mapping documented in
`validation/hillstrom/README.md` (that mapping is the main free parameter),
and consider scoring "engaged" instead of "clicked" as the visit analogue.

### 4. Robustness audit (Rung 3, plan §10 — needs #1)

Not started. Sweep model / temperature / prompt paraphrase / seed on a fixed
campaign, report variance decomposition + ablations (no-network vs network,
archetype-cache vs full). Suggested home: `validation/robustness.py`. The
BehaviorSpace `run_experiment` tool can drive the replicate sweeps.

### 5. Calibration with real data (ongoing)

`calibrate` works today (benchmark anchoring + CSV fitting is tested). What
remains is *using* it with a real past campaign's stats — yours or a pilot
partner's (plan §10 Rung 4: one real case study beats all benchmarks).

### 6. Polish / ship (plan Phase 6)

- README section + demo GIF (run the busy-parents campaign with
  `run_campaign(..., engine="netlogo", watch=true)` and screen-record the
  NetLogo window lighting up).
- v3 stimulus: image ads via a vision model (Gemma-3-4B) — `stimulus.py`
  has the `visual_description` field ready; only the VLM call is missing.
- Desktop app: wire `desktop-app/` (Tauri scaffold) to the server later.
- Paper: validation suite + ablations → GABM methods paper (ESSA/JASSS or
  an LLM-agents workshop).

---

## How to run what exists today (no LLM needed)

```powershell
uv run pytest tests/market -q                      # 79 tests
uv run python validation/spike/spike.py            # 20-persona reaction table
uv run python validation/bass_diffusion.py         # S-curve validation
uv run python validation/hillstrom/backtest.py     # baseline backtest
uv run --extra dashboard streamlit run dashboard/app.py   # results browser
```

Or conversationally through any MCP client connected to this server:
`generate_audience` → `create_campaign` → `run_campaign` →
`get_campaign_report` → `interview_persona`. In mock mode every report and
interview carries an explicit "heuristic backend" disclaimer, so nothing
pretends to be an LLM result.
