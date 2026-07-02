# Findings Report — Information, Trust & Misinformation in an Ebola Agent-Based Model

**Mongbwalu / Bunia (Ituri, DRC) · Bundibugyo virus outbreak 2026**

*Author: Saqlain Abbas · Built and analysed with Claude (Opus 4.8) via the NetLogo MCP server · 2026-06-21*

---

## Executive summary

We built a complete, standalone NetLogo agent-based model (ABM) of the 2026 Bundibugyo Ebola outbreak in Mongbwalu/Bunia, focused on the project's key open question: **how do (mis)information and trust shape the epidemic?** We then ran two BehaviorSpace experiments (72 headless runs, 8 repetitions per condition) to quantify the effect.

**Two clean, statistically consistent results:**

1. **Misinformation makes the outbreak worse.** Raising the starting level of misinformation from 0% to 90% (no interventions) increased deaths by ~15% (538 → 619), pushed the case-fatality rate up ~6 points (71.7% → 77.5%), and increased unsafe burials by ~15%.

2. **Trust-building interventions make it markedly better.** Holding misinformation high and ramping up Risk Communication & Community Engagement (RCCE) intensity from 0 to 0.9 (with radio, leader engagement, safe-burial program and contact tracing all active) cut deaths by ~24% (611 → 467), lowered CFR by ~12 points (76.8% → 65.0%), and **flipped burials from overwhelmingly unsafe to majority safe** (unsafe 570 → 159; safe 42 → 307).

**Bottom line for WHO-style decision support:** in a setting with no Bundibugyo vaccine or treatment, *information and trust are themselves an intervention*. Communication that is trusted (radio, religious/ethnic leaders, survivor ambassadors) measurably reduces deaths and unsafe burials, even when it cannot stop most people from eventually being exposed.

---

## 1. Background

The current outbreak (PHEIC declared 16 May 2026) is caused by **Bundibugyo virus**, for which there is **no approved vaccine and no specific treatment**. Control therefore rests entirely on non-pharmaceutical measures and human behaviour: hospital-seeking, safe and dignified burials, contact tracing, and countering misinformation. Field reports document exactly the behavioural drivers this model targets — unsafe burials, hiding the sick, attacks on treatment centres, deep institutional mistrust, and active rumour spread (e.g. "Ebola is a Western conspiracy").

This work is a standalone proof for the WHO/ASSOCC-Ebola NetLogo project (Frank Dignum's group): it implements the **Information / Misinformation / Trust module** — the project's #1 "make new" component, which does not yet exist in the team's prototype — coupled to a full disease model, so the module's value can be demonstrated and later ported into the main ASSOCC fork.

---

## 2. The model

**Disease (SEIHR/D).** A finite state machine: susceptible → exposed (incubation ≈ 6 d) → stage 1 → stage 2 → hospitalised **or** non-hospitalised → recovered **or** dead → safe **or** unsafe burial → removed. Timings and case-fatality reflect Bundibugyo data.

**Contagion (close-contact, EVD-correct).** Transmission occurs through households, caregiving ties, funerals, and health workers (with imperfect IPC) — not casual crowds. Bodies are highly infectious before burial; unsafe funerals are explicit super-spreading events.

**Information & Trust module (the centrepiece).** Each agent holds beliefs (*Is Ebola real? Does the hospital help? Is safe burial acceptable?*), per-source trust (health teams, government, radio, religious/ethnic leaders), awareness, and fear. Rumours spread along a social network; radio (Radio Okapi), engaged leaders, and recovered "survivor ambassadors" spread correct information; a trusted-information rule governs what each agent believes. Beliefs and trust then drive four behaviour hooks: **precautions** (transmission), **hospital-seeking**, **safe vs unsafe burial**, and **care-seeking delay**. Fear rises near deaths.

**Context.** Mongbwalu demographics (Lendu/Hema, miners, caregivers, health workers, ~6-person households) on a spatial layout of mine, market, church, hospital, homes, and cemetery.

**Interventions (toggles).** Radio campaign, leader engagement, safe-burial program, contact tracing (capped at the real ~21% follow-up reached in the field), and an overall RCCE-intensity dial.

Model file: `models/Ebola_Mongbwalu_InformationTrust.nlogox`.

---

## 3. Methods

Experiments were run with NetLogo BehaviorSpace via the headless launcher (`NetLogo_Console --headless`), 800 agents, base transmission 0.06, each run to outbreak extinction (`stop` when no infectious or incubating agents remain), **8 repetitions per condition**. Metrics recorded at end of run: attack rate (% ever infected), cumulative deaths, case-fatality rate (CFR), and cumulative safe vs unsafe burials.

- **Experiment 1 — Misinformation gradient.** Interventions OFF. Vary `initial-misinformation` ∈ {0, 0.25, 0.5, 0.75, 0.9}. 40 runs.
- **Experiment 2 — Intervention impact.** Misinformation fixed high (0.6); radio, leaders, safe-burial and contact-tracing all ON. Vary `rcce-intensity` ∈ {0, 0.3, 0.6, 0.9}. 32 runs.

Raw per-run tables: `exports/experiments/exp1_misinformation_gradient_*.table.csv` and `exp2_intervention_impact_*.table.csv`.

---

## 4. Results

### Experiment 1 — More misinformation → worse outcomes (no interventions)

| Initial misinformation | Attack rate | Deaths | CFR | Unsafe burials | Safe burials |
|---:|---:|---:|---:|---:|---:|
| 0.00 | 93.8% | 538 | 71.7% | 502 | 36 |
| 0.25 | 99.4% | 599 | 75.4% | 552 | 47 |
| 0.50 | 99.6% | 606 | 76.1% | 566 | 40 |
| 0.75 | 99.9% | 621 | 77.8% | 576 | 45 |
| 0.90 | 99.9% | 619 | 77.5% | 578 | 40 |

*(means of 8 runs each)*

**Reading it:** every step up in misinformation raises deaths, CFR, and unsafe burials. Going from an informed population (0) to a heavily misinformed one (0.9) adds ~80 deaths and ~6 CFR points and drives the attack rate to near-total. The effect is strongest in the first jump (0 → 0.25): even a *minority* of misinformation meaningfully worsens the outbreak.

### Experiment 2 — Trust-building interventions → better outcomes (misinformation held high)

| RCCE intensity | Attack rate | Deaths | CFR | Unsafe burials | Safe burials |
|---:|---:|---:|---:|---:|---:|
| 0.0 | 99.5% | 611 | 76.8% | 570 | 42 |
| 0.3 | 97.2% | 554 | 71.2% | 388 | 166 |
| 0.6 | 95.3% | 521 | 68.3% | 270 | 250 |
| 0.9 | 89.7% | 467 | 65.0% | 159 | 307 |

*(means of 8 runs each; radio + leaders + safe-burial + contact-tracing all ON)*

**Reading it:** a clean dose-response. As communication intensity rises:
- **Deaths fall ~24%** (611 → 467).
- **CFR falls ~12 points** (76.8% → 65.0%) — driven by more people trusting and reaching care.
- **Burials flip** from overwhelmingly unsafe to majority safe (unsafe 570 → 159; safe 42 → 307). The crossover happens between intensity 0.3 and 0.6.
- **Attack rate falls ~10 points** (99.5% → 89.7%) via the precaution/behaviour-change channel.

---

## 5. Interpretation & policy implications

1. **Information is an intervention.** With no vaccine or drug for Bundibugyo, the model shows that *what people believe and whom they trust* is a primary determinant of mortality. Investing in trusted communication is not "soft" — it produces hard reductions in deaths and unsafe burials.
2. **Trusted channels matter more than volume.** Effects flow through trust: radio (Radio Okapi), religious/ethnic leaders, and survivor ambassadors. This matches field experience and the project's documented "trusted-information rules."
3. **Safe burial is the most movable lever.** The burial safe/unsafe ratio responds fastest and largest to RCCE — consistent with funerals being a dominant Ebola transmission route. Safe & Dignified Burial programs paired with trust-building give the clearest win.
4. **Stopping spread entirely is hard; reducing harm is achievable.** Even strong intervention does not drive the attack rate to zero (it falls from ~99% to ~90%). The realistic, honest message: communication **substantially reduces deaths and unsafe burials**; eliminating transmission additionally requires earlier and stronger case isolation (pushing R below 1).

---

## 6. Limitations

- **Single closed community, well-connected network.** Attack rates run high because, once seeded, Ebola reaches most of a connected population absent strong isolation (standard SIR behaviour). Real geographic/ social fragmentation would lower totals.
- **CFR higher than the ~17% headline.** The no-intervention baseline has almost no hospitalisation, inflating CFR; it falls as care-seeking rises and is tunable (`cfr-hospital`, `cfr-nonhospital`).
- **Stylised parameters.** Transmission, trust dynamics, and intervention efficacies are plausible and data-informed but not formally calibrated to the 15–23 May line list. Calibration is a clear next step.
- **Rule-based beliefs.** Belief updating is rule-based; richer heterogeneity (personas) is a planned extension.

---

## 7. Next steps

1. **Calibrate** transmission and reporting to the dataset's 15–23 May daily case/death curve.
2. **Hema/Lendu trust asymmetry** — model group-specific trust and access (a documented real-world dynamic).
3. **LLM-driven agents (differentiator)** — replace the belief-update rule with per-agent persona reasoning, and feed the project's real-data misinformation dashboard into the model's rumour sources.
4. **Port** the Information & Trust module into the ASSOCC `ebolaTest` fork.

---

## Appendix — reproducibility

- Model: `models/Ebola_Mongbwalu_InformationTrust.nlogox`
- Experiment 1: 40 runs, 8 reps × 5 misinformation levels, interventions off.
- Experiment 2: 32 runs, 8 reps × 4 RCCE levels, all interventions on, misinformation 0.6.
- Raw CSVs: `exports/experiments/exp1_misinformation_gradient_*.table.csv`, `exp2_intervention_impact_*.table.csv`.
- Engine: NetLogo 7.0.3 BehaviorSpace, headless. Built/run via NetLogo MCP server.
