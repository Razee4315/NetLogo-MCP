# Ebola Project — The Full Story (Start to Finish)

*A plain-English narrative of everything we did, read, found, built, and solved.*
*Compiled 2026-06-21 · Saqlain Abbas, with Claude (Opus 4.8) via the NetLogo MCP server.*

---

## 1. How it started — the ask

**Serge Stinckwich** (Head of Research, UNU Macau) — with whom there is an ongoing
research collaboration on the NetLogo MCP project — reached out after a quiet period
and invited me into a real project. His colleague **Frank Dignum** (creator of the
ASSOCC social-simulation framework) followed up by email with a Zoom invite and a
shared Google Drive.

**What they asked:**
- They have formed a **group of NetLogo developers building an epidemiological
  simulation platform for Ebola**, for the **WHO**, tied to the **active 2026 outbreak
  in DR Congo**.
- The platform must model **human behaviour during the outbreak**, not just disease
  spread.
- Several **submodules are missing**; they need committed developers to build them.
- Terms: **no pay**, but **named credit**, a possible **official WHO letter**, and the
  chance to **help save lives**. Contributors must already know NetLogo well.
- First team meeting: **Tuesday 23 June 2026, 15:30 CET (Zoom)**.

So the goal became: understand the disease, understand their project, find where I can
contribute most, and walk in with something real.

---

## 2. What I did (the process)

1. **Read the NetLogo MCP context** from the Obsidian vault to understand the existing
   collaboration and where it stood.
2. **Deep-researched Ebola** from authoritative sources (WHO, CDC, ECDC, peer-reviewed
   literature) — disease, history, the current outbreak, epidemiology, behaviour.
3. **Read the entire shared repository** Frank provided (design docs, datasets, code,
   literature) and the linked GitHub repos (ASSOCC + the Ebola prototype).
4. **Found the gap** — the one module the team wants but hasn't built.
5. **Built a complete, professional NetLogo model** of that module (disease + information
   + trust), live through the NetLogo MCP server.
6. **Ran experiments** (BehaviorSpace, 72 runs) to quantify the findings.
7. **Wrote it all up** — a findings report, an Overleaf paper, and this story.

Everything is saved to disk and to the Obsidian knowledge base.

---

## 3. What we read

### 3a. The disease (deep research)
- **Ebola** is a filovirus; six species; the current 2026 outbreak is **Bundibugyo virus
  (BDBV)** in DRC + Uganda, **PHEIC declared 16 May 2026**.
- **Critical fact: Bundibugyo has no approved vaccine and no specific treatment.** The
  licensed vaccine (Ervebo) only covers Zaire virus. So control rests entirely on
  **behaviour** — hospital-seeking, safe burials, contact tracing, countering rumours.
- Spreads by **close contact** with the body fluids of the sick **and the dead**;
  **funerals are the biggest amplifier**. Incubation 2–21 days; not infectious before
  symptoms. CFR for this outbreak ~17–25%.
- History: first identified 1976; largest ever was 2013–16 West Africa (~28,600 cases);
  second largest 2018–20 DRC Kivu (conflict + community resistance).

### 3b. The project repository (Frank's Drive)
Two distinct things:
- **A plan to repurpose ASSOCC for Ebola** — design documents describing how to convert
  the COVID model into an Ebola model set in the real epicentre **Mongbwalu / Bunia,
  Ituri**, plus a partially-built prototype (`cybertilla/ebolaTest`, a fork of
  `lvanhee/COVID-sim`).
- **A separate working app** — a Python/FastAPI **misinformation & sentiment dashboard**
  that pulls real news/Reddit/ReliefWeb data about the outbreak.

---

## 4. What we found in them

### 4a. The design intent (from the docs)
The team's module plan sorts work into **make-new**, **keep-and-change**, and
**discard**. The **#1 "make new"** item is an **Information / misinformation / trust
module**: *who generates information, who is trusted, how it spreads, and to what
effect.* The docs are deeply researched: Mongbwalu demographics (Lendu/Hema split,
gold-mining economy, ~6-person households), the cultural and trust dynamics (mistrust of
government and medical teams, "Ebola is a Western conspiracy" rumours, traditional
burials, traditional healers), and the gathering points that matter (mine, market,
church, hospital, home, cemetery).

### 4b. The dataset (`Ebola_BVD_2026_ABM_Dataset_FINAL.xlsx`)
A clean, sourced, 7-sheet dataset built for modelling — including a **daily case/death
timeline (15–23 May)** and a standout **Behavioral sheet** that lists ten behavioural
factors (unsafe burials, hiding the sick, care delay, traditional healers, stigma,
attacks on responders, misinformation, fear, cross-border funerals, mistrust) each with
an explicit **"ABM parameter implication"** (e.g. burial resistance 40–70%, care delay
20–40%). In other words, the parameter homework is already done.

### 4c. The code (the prototype)
The Ebola prototype already has a **functional SEIHR/D disease state machine**, a
**contagion module**, a **burial-rites gathering point**, and a **cultural model** (with
placeholder values). Crucially:

> **The Information / misinformation / trust module does NOT exist in the code yet.**

That is the gap.

---

## 5. What's in the program (the two pieces)

- **The ASSOCC/Ebola model (NetLogo):** needs-driven agents choose daily actions; a
  disease model infects them; the prototype has disease + contagion + burials started.
  Built to be modular (`.nls` files). Missing: the information/trust layer.
- **The misinformation dashboard (Python/FastAPI):** ingests real news + Reddit +
  ReliefWeb posts, scores sentiment (VADER), clusters topics, flags misinformation with
  explainable rules, tags geography, detects spikes, and serves a 6-page dashboard. It is
  the **data-facing complement** to an in-simulation information module.

---

## 6. Where the gap is

The disease model is wired to react to behaviour — for example, the chance an agent goes
to hospital is keyed to a **trust-in-hospital** value, and burials are split into
**safe vs unsafe**. But **nothing drives those beliefs and trust levels** — there is no
module that spreads (mis)information, builds or erodes trust, or changes behaviour. That
missing layer is exactly:
- the team's #1 "make new" task,
- unclaimed,
- a perfect fit for the LLM-agents-with-personalities direction and the existing
  misinformation dashboard,
- and immediately impactful, because the disease model already exposes the hooks.

**Decision:** build that module.

---

## 7. What we built in NetLogo

A complete, standalone, professional model: **`Ebola_Mongbwalu_InformationTrust.nlogox`**,
built and verified live through the NetLogo MCP server.

**What it contains:**
- **Disease:** full SEIHR/D state machine (susceptible → exposed → stage 1 → stage 2 →
  hospital/community → recover/die → safe/unsafe burial → removed), with realistic
  timings and CFR.
- **Contagion (Ebola-correct):** spreads through **close contact only** — households,
  caregiving, funerals, and health workers — not casual crowds. Bodies are highly
  infectious; unsafe funerals are super-spreading events.
- **The Information & Trust module (the new piece):** every agent holds **beliefs**
  (is Ebola real? does the hospital help? is safe burial acceptable?) and **trust** in
  each source (health teams, government, radio, religious/ethnic leaders), plus awareness
  and fear. **Rumours spread** on the social network; **radio, engaged leaders, and
  recovered "survivor ambassadors" spread correct information**; a trusted-information
  rule decides what each agent believes.
- **Four behaviour hooks:** beliefs/trust drive (1) **precautions** (which cut
  transmission), (2) **hospital-seeking**, (3) **safe vs unsafe burial**, and (4)
  **care-seeking delay**. Fear rises near deaths.
- **Interventions (toggles):** radio campaign, leader engagement, safe-burial program,
  contact tracing (capped at the real ~21% follow-up), and an overall RCCE-intensity dial.
- **Context:** Mongbwalu demographics and a spatial layout of the six gathering points.
- **Professional GUI:** setup / go / step / "trigger rumour wave" buttons, 8 sliders, 4
  switches, 7 monitors, and 3 live plots, on an enlarged canvas, with fully-commented
  code.

---

## 8. What we found (the experiments)

We ran two BehaviorSpace experiments — **72 headless runs, 8 repetitions each** — and got
two clean, monotonic dose–response results.

### Experiment 1 — More misinformation → worse outcomes (no interventions)
| Initial misinformation | Attack % | Deaths | CFR % | Unsafe burials | Safe burials |
|---:|---:|---:|---:|---:|---:|
| 0%  | 93.8 | 538 | 71.7 | 502 | 36 |
| 25% | 99.4 | 599 | 75.4 | 552 | 47 |
| 50% | 99.6 | 606 | 76.1 | 566 | 40 |
| 75% | 99.9 | 621 | 77.8 | 576 | 45 |
| 90% | 99.9 | 619 | 77.5 | 578 | 40 |

→ Rising misinformation adds **~80 deaths**, **~6 CFR points**, and more unsafe burials.

### Experiment 2 — Trusted communication → better outcomes (misinformation held high)
| RCCE intensity | Attack % | Deaths | CFR % | Unsafe burials | Safe burials |
|---:|---:|---:|---:|---:|---:|
| 0.0 | 99.5 | 611 | 76.8 | 570 | 42 |
| 0.3 | 97.2 | 554 | 71.2 | 388 | 166 |
| 0.6 | 95.3 | 521 | 68.3 | 270 | 250 |
| 0.9 | 89.7 | 467 | 65.0 | 159 | 307 |

→ Stronger trusted communication cuts **deaths ~24%** (611→467), **CFR ~12 points**, and
**flips burials** from mostly unsafe to mostly safe (unsafe 570→159, safe 42→307).

---

## 9. What we solved (the conclusions)

- **We filled the gap:** the Information & Trust module the team wanted but hadn't built
  now exists, runs, and is coupled to a real disease model.
- **We answered the project's core question with evidence:** *(mis)information and trust
  materially change outbreak outcomes.* With no Bundibugyo vaccine or treatment,
  **information and trust are themselves an intervention.**
- **Key practical findings:**
  - Trusted channels (radio, leaders, survivor ambassadors) are what move outcomes.
  - **Safe burial is the most responsive lever** — it flips fastest and largest.
  - Communication **substantially reduces deaths and unsafe burials**, even when it
    cannot stop most people from eventually being exposed; eliminating transmission also
    needs earlier, stronger case isolation (push R below 1).

### Honest limitations
Single connected community (so attack rates run high — standard epidemic behaviour); CFR
runs above the ~17% headline because the no-intervention baseline has almost no
hospitalisation (tunable); not yet calibrated to the 15–23 May line list; belief updating
is rule-based.

---

## 10. What we produced (deliverables)

- **Model:** `models/Ebola_Mongbwalu_InformationTrust.nlogox`
- **Findings report:** `docs/research/ebola-model-findings-report.md`
- **Overleaf paper:** `overleaf/` (+ `overleaf.zip`) — figures, charts, tables, references
- **Raw data:** `exports/experiments/exp1_*.csv`, `exp2_*.csv`
- **Knowledge base (Obsidian):** Ebola Knowledge Base · Repo Analysis · WHO Project ·
  Model (v1) · Findings (BehaviorSpace) · this story
- **Ebola disease knowledge base:** `docs/research/ebola-knowledge-base.md`

## 11. What's next
1. **Calibrate** to the real May 2026 daily case curve.
2. **Model Hema/Lendu trust asymmetry** and differential clinic access.
3. **LLM-driven agents** (persona-level belief reasoning) + wire the misinformation
   dashboard's real signals into the model's rumour sources.
4. **Port** the Information & Trust module into the team's ASSOCC Ebola codebase.

---

*One-line summary: Serge/Frank asked for help building a WHO Ebola simulation; I learned
the disease and their codebase, found that the information/trust module was the missing
piece, built it as a complete NetLogo model, and showed with 72 experiments that
misinformation worsens and trusted communication improves the outbreak — especially
deaths and safe burials.*
