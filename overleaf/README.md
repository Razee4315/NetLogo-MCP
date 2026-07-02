# Overleaf package — Ebola Information & Trust ABM report

This folder is a self-contained, Overleaf-ready LaTeX project for the report
*"Information, Trust, and Misinformation in an Agent-Based Model of the 2026
Bundibugyo Ebola Outbreak."*

## How to use on Overleaf
1. Go to Overleaf → **New Project → Upload Project**.
2. Upload the **`overleaf.zip`** (or drag the contents of this folder in).
3. Make sure the compiler is **pdfLaTeX** (Menu → Compiler → pdfLaTeX). Recompile.

That's it — it compiles as-is. The two result charts are drawn natively with
**pgfplots/TikZ** (no Python/matplotlib needed), and the bibliography is inline
(`thebibliography`), so there is no separate BibTeX pass.

## Contents
- `main.tex` — the full paper (intro, model, methods, results, discussion, refs).
- `figures/model_screenshot.png` — the running NetLogo model (Mongbwalu layout).
- `supplementary/`
  - `Ebola_Mongbwalu_InformationTrust.nlogox` — the NetLogo model itself.
  - `exp1_misinformation_gradient.csv` — raw BehaviorSpace data, Experiment 1.
  - `exp2_intervention_impact.csv` — raw BehaviorSpace data, Experiment 2.

## What the paper covers
- The 2026 Bundibugyo outbreak context (no vaccine/treatment → behaviour is the lever).
- The model: SEIHR/D disease, close-contact contagion, and the Information & Trust module.
- Two BehaviorSpace experiments (72 runs, 8 reps each): misinformation gradient and
  intervention/RCCE impact, with dose–response charts and tables.
- Discussion, limitations, and next steps.

## To edit the title/author
Open `main.tex` and edit the `\title{...}` and `\author[1]{...}` lines near the top.
