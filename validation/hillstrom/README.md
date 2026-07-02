# Hillstrom Email Backtest (Rung 2 — plan.md §10)

The **MineThatData E-Mail Analytics Challenge** dataset (Kevin Hillstrom,
2008): 64,000 real customers of an e-commerce retailer, randomly assigned to
receive a *Mens merchandise email*, a *Womens merchandise email*, or *no
email*, with two weeks of tracked outcomes (site visit, conversion, spend)
plus customer covariates.

This is the headline validation target: build personas **from the real
covariate distribution**, simulate the email send, and compare simulated vs
real outcomes **by segment**.

## Setup

1. Download the CSV (public, ~5 MB):

   http://www.minethatdata.com/Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv

2. Save it as `validation/hillstrom/hillstrom.csv`

3. Run the backtest:

   ```
   uv run python validation/hillstrom/backtest.py
   ```

   Add `SYNTH_LLM_MODE=live` for LLM cognition (the number that matters for
   the paper); without it the heuristic baseline is scored — useful as the
   rule-based baseline the LLM must beat.

## What is scored

- **Segment ranking (primary):** Spearman correlation between simulated and
  real *visit rates* across segments (zip_code x newbie x history tier).
  Directional agreement is the honest first claim.
- **Absolute rates (secondary):** raw and calibrated visit rate vs the real
  ~15% (womens email) / ~2 week window.

## Covariate -> persona mapping (documented assumptions)

| dataset column | persona field | mapping |
| --- | --- | --- |
| zip_code | location | urban/suburban/rural verbatim |
| newbie | brand_loyalty | newbie=1 -> low loyalty (0.2±0.1) else 0.55±0.15 |
| history | income_bracket + price_sensitivity | spend tercile -> low/mid/high |
| womens (bought womens before) | category_involvement | 1 -> 0.65±0.15 else 0.30±0.15 |
| recency (months) | channels.email | recent buyers read brand email more |
| channel (Phone/Web/Multichannel) | channels.email modifier | multichannel +0.1 |

Everything else uses population defaults. The mapping is a modeling choice —
report it, sweep it in the robustness audit.
