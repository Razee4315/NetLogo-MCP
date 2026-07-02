# Cognition Model Bake-off (Phase 2 — run when a local LLM is installed)

Goal: pick the default local model for persona cognition. Run each candidate
through the same fixed panel and score four things.

## Candidates

| model | ollama tag | size |
| --- | --- | --- |
| Qwen3 4B Instruct | `qwen3:4b` | 4B |
| Phi-4-mini | `phi4-mini` | 3.8B |
| Gemma 3 4B | `gemma3:4b` | 4B (vision-capable) |
| Llama 3.2 3B | `llama3.2:3b` | 3B |
| Qwen3 8B (if VRAM allows) | `qwen3:8b` | 8B |
| Claude Haiku (cloud ceiling) | via SYNTH_LLM_BASE_URL | — |

## Protocol

For each model:

```powershell
$env:SYNTH_LLM_MODE = "live"
$env:SYNTH_LLM_MODEL = "<tag>"
uv run python validation/spike/spike.py
```

Then a bigger panel (100 personas):

```powershell
uv run python -c "..."   # or run the busy-parents example campaign, fidelity=full
```

## Scorecard (fill in)

| model | JSON compliance % | decision-path diversity | skeptic-vs-enthusiast open-rate gap | calls/sec | verdict |
| --- | --- | --- | --- | --- | --- |
| qwen3:4b | | | | | |
| phi4-mini | | | | | |
| gemma3:4b | | | | | |
| llama3.2:3b | | | | | |
| haiku (ceiling) | | | | | |

Scoring notes:
- **JSON compliance**: fraction of calls that parse first try (the client
  retries, but retries cost latency).
- **Diversity**: entropy of (stage1, action) paths across the panel — a
  model that answers identically for everyone is useless here.
- **Discrimination**: open-rate gap between high-involvement/high-trust and
  low-involvement/skeptic personas. Bigger gap = persona conditioning works.
- **Throughput**: with `OLLAMA_NUM_PARALLEL=8` set.

Pick: best diversity x discrimination subject to compliance > 95%.
Record the decision and numbers here; the default lives in
`market/config.py` (`SYNTH_LLM_MODEL`).
