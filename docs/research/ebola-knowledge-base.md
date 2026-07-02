# Ebola Virus Disease — Knowledge Base for the WHO Simulation Project

> Compiled 2026-06-21 for the WHO-facing NetLogo / agent-based Ebola simulation project (Serge Stinckwich group).
> Sources: WHO, CDC, ECDC, peer-reviewed literature. Citations inline; full list at bottom.
> Emphasis: facts needed to build an epidemiological + human-behavior simulation platform.

---

## 0. TL;DR for the project

- **There is an ACTIVE outbreak right now.** Declared a **PHEIC on 15–16 May 2026**. Caused by **Bundibugyo virus (BDBV)** in **DRC (Ituri, North & South Kivu)** and **Uganda**. As of mid-June 2026: roughly **~837–956 confirmed cases / ~196–247 deaths in DRC**, **19 cases / 2 deaths in Uganda**, CFR ~25%. (Case counts were revised down then up — data is noisy, typical of an active conflict-zone outbreak.)
- **Critical modeling fact:** Bundibugyo has **NO approved vaccine and NO approved specific treatment.** Ervebo (the licensed vaccine) targets *Zaire* virus only; WHO advised against using it here due to limited cross-protection. So **non-pharmaceutical interventions and human behavior are the main levers** — exactly what your simulation should model.
- **Behavior dominates the dynamics.** Funeral/burial practices, community trust, healthcare-seeking, and compliance drive a large share of transmission. Models show behavior change substantially cuts outbreak size and duration. This is the project's core value-add.

---

## 1. The Disease Itself

### Classification
- **Family:** *Filoviridae*. **Genus:** *Orthoebolavirus* (recently reclassified; older literature says genus *Ebolavirus*).
- **Six species:**
  1. **Zaire ebolavirus (EBOV)** — most lethal, most outbreaks. CFR ~60–90%.
  2. **Sudan ebolavirus (SUDV)** — CFR ~40–60%. No licensed vaccine.
  3. **Bundibugyo ebolavirus (BDBV)** — lower CFR (~25–55%); **the current 2026 outbreak**. No licensed vaccine.
  4. **Taï Forest ebolavirus (TAFV)** — single non-fatal human case (Côte d'Ivoire 1994).
  5. **Reston ebolavirus (RESTV)** — **non-pathogenic to humans**; infects primates/pigs (Asia/Philippines).
  6. **Bombali ebolavirus (BOMV)** — detected in bats; no known human disease.
- Three species (Zaire, Sudan, Bundibugyo) have caused **large human outbreaks**.

### Natural reservoir & spillover
- **Fruit bats of the *Pteropodidae* family** are the suspected natural hosts (WHO).
- **Spillover to humans** via contact with infected wildlife: bats, non-human primates (apes, monkeys), forest antelope, porcupines — often via hunting/butchering **bushmeat**.

### Transmission (human-to-human)
- Direct contact with **blood or body fluids** (saliva, sweat, vomit, feces, urine, breast milk, semen) of a **symptomatic** or **deceased** person.
- Contact with **contaminated surfaces/materials** (bedding, clothing, needles).
- **Dead bodies remain highly infectious** → **funeral/burial rituals** (washing, touching the body) are a major amplifier.
- **Key rule for modeling:** people are **NOT infectious before symptom onset** (no pre-symptomatic transmission). This shapes the SEIR structure.

### Clinical course
- **Incubation period:** **2–21 days** (mean ~4–10 days).
- **Symptoms:** sudden fever, fatigue, muscle pain, headache, sore throat → then vomiting, diarrhea, rash, impaired kidney/liver function. **Hemorrhage (bleeding) is less frequent and occurs late**, contrary to popular image.
- **Case fatality rate (CFR):** average ~**50%**, historically **25–90%**, varies by species and care quality.

### Diagnosis
- **RT-PCR** (mainstay), ELISA antibody-capture, antigen-capture detection, virus isolation in cell culture. Rapid mobile labs increasingly deployed near outbreaks.

### Viral persistence in survivors (matters for re-emergence!)
- Virus persists in **immune-privileged sites**: **testes/semen, eyes, central nervous system, placenta/amniotic fluid, breast milk**.
- **Sexual transmission documented up to ~15 months** after recovery.
- **Several recent outbreaks (2021 Guinea, 2021 DRC) were traced to persistent infection in survivors** re-igniting years later — a key feature for long-horizon models.

---

## 2. Treatment & Prevention

### Treatments (Zaire virus only, FDA/WHO-recognized)
- **Inmazeb** (atoltivimab + maftivimab + odesivimab; REGN-EB3) — triple monoclonal antibody. FDA-approved **Oct 2020**. In the **PALM trial** (2018–20 DRC), 28-day mortality ~**34%** vs ~49% for ZMapp control.
- **Ebanga** (ansuvimab / mAb114) — single monoclonal antibody, also strong survival benefit.
- **Both work best given EARLY** (low viral load, first days of symptoms).
- **Supportive care** ("optimized supportive care"): aggressive IV rehydration, electrolyte balance, treating co-infections — improves survival even without specific antivirals.
- ⚠️ **No approved treatment for Sudan or Bundibugyo** — only investigational (remdesivir, MBP-134/broad filovirus mAb, etc.), tested via WHO platforms (e.g., PARTNERS/PALM-style trials).

### Vaccines (Zaire virus only)
- **Ervebo (rVSV-ZEBOV-GP, Merck)** — single-dose, live-attenuated. WHO prequalified / FDA-approved **Dec 2019**. **~100% effective** ≥10 days post-vaccination in the Guinea ring-vaccination trial.
- **Zabdeno + Mvabea (Ad26.ZEBOV + MVA-BN-Filo, Janssen)** — **two-dose** regimen for preventive use (not outbreak ring use, due to the dose interval).
- **No licensed vaccine for Sudan or Bundibugyo** (candidates in trials, e.g., ChAd3-SUDV).

### Strategies
- **Ring vaccination:** vaccinate contacts + contacts-of-contacts of each confirmed case → builds an immune "ring" around the outbreak. Core outbreak tactic for Zaire EVD.
- **Preventive vaccination** of frontline/health workers (e.g., Sierra Leone 2024 campaign).
- **Infection Prevention & Control (IPC):** PPE, isolation/Ebola treatment units (ETUs), **Safe and Dignified Burials (SDB)**, contact tracing, safe sex counseling for survivors, decontamination.

---

## 3. Outbreak History (1976 → 2026)

### Origin
- **1976, first recognition** — two simultaneous outbreaks:
  - **Zaire/DRC, Yambuku** (Équateur): **318 cases / 280 deaths (~88% CFR)** — Zaire virus. Named after the nearby Ebola River.
  - **Sudan (Nzara/Maridi):** **284 cases / 151 deaths (~53%)** — Sudan virus.

### Major / notable outbreaks
| Year | Place | Species | Cases | Deaths | CFR |
|---|---|---|---|---|---|
| 1976 | DRC (Yambuku) | Zaire | 318 | 280 | 88% |
| 1976 | Sudan | Sudan | 284 | 151 | 53% |
| 1995 | DRC (Kikwit) | Zaire | 315 | 254 | 81% |
| 2000 | Uganda (Gulu) | Sudan | 425 | 224 | 53% |
| 2003 | Rep. Congo | Zaire | 143 | 128 | 89% |
| 2007 | DRC | Zaire | 264 | 187 | 71% |
| 2007 | Uganda (Bundibugyo) | **Bundibugyo (first ID)** | 131 | 42 | 32% |
| 2013–16 | **West Africa** (Guinea/Liberia/Sierra Leone) | Zaire | **~28,600** | **~11,300** | ~40% |
| 2018–20 | **DRC (North Kivu/Ituri)** | Zaire | **3,470** | **2,287** | 66% |
| 2022 | Uganda (Mubende) | Sudan | 164 | 55 | 34% |
| 2025 | Uganda (Kampala) | Sudan | ~14 | 4 | 30% |
| 2025 | DRC (Bulape, Kasai) | Zaire | 64 | 45 | 70% |
| **2026** | **DRC + Uganda** | **Bundibugyo** | **ongoing** | **ongoing** | **~25%** |

### The two defining epidemics
- **2013–2016 West Africa epidemic** — **largest ever**. ~28,600 cases, ~11,300 deaths across Guinea, Liberia, Sierra Leone; exported cases to Nigeria, Mali, Senegal, Spain, UK, US, Italy. Causes of scale: cross-border spread, weak health systems, dense urban transmission, delayed response, unsafe burials, community distrust. Triggered the **first Ebola PHEIC (8 Aug 2014)** and the modern vaccine/treatment pipeline.
- **2018–2020 DRC (Kivu)** — **second largest** (~3,470 cases). First to use Ervebo + monoclonal antibodies at scale via ring vaccination + the PALM trial. Defined by **armed conflict, attacks on health workers, and community resistance** — the template for "behavior + insecurity" modeling.

### Sudan-virus track (no vaccine) — Uganda
- Recurrent: 2000 (Gulu, 425 cases), 2012, 2022 (Mubende, 164), 2025 (Kampala). Important because **no licensed countermeasures** → behavior/IPC-driven control.

---

## 4. WHO's Role

- **PHEIC declarations for Ebola:** West Africa (8 Aug 2014), DRC Kivu (17 Jul 2019), and the **current 2026 outbreak (15–16 May 2026)**. A PHEIC is the highest alarm under the **International Health Regulations (IHR 2005)**, triggering international coordination, funding, and recommendations.
- **R&D Blueprint** — created in response to 2014–16 to fast-track vaccines/diagnostics/therapeutics for high-threat pathogens; Ebola was the prototype.
- **Global Ebola vaccine stockpile** — since 2021, **500,000-dose** emergency stockpile of Ervebo, governed by the **ICG (International Coordinating Group)**, procured via **UNICEF**, funded by **Gavi**; accessible to any country.
- **Operational role:** coordination, surveillance, contact tracing support, deploying ETUs, lab networks, Safe & Dignified Burial protocols, risk communication & community engagement (RCCE), and situation reports / Disease Outbreak News (DON).
- **Current outbreak pages:** `who.int/emergencies/situations/ebola-outbreak---drc-2026` and `afro.who.int`.

---

## 5. Epidemiology & Modeling (parameters you'll need)

### Reproduction number (R0)
- Historical (Congo 1995, Uganda 2000): **R0 ≈ 1.3–2.7**.
- 2014 West Africa maximum-likelihood estimates: **Guinea 1.51, Sierra Leone 2.53, Liberia 1.59** (other studies 1.65–2.18 for Sierra Leone).
- Behavior-model fits (SIRD): **R0 ≈ 1.71 (Liberia), 2.0 (Sierra Leone)** under controlled behavior.
- **Rule of thumb: R0 typically ~1.5–2.5.** A meaningful share is attributable to **post-death (funeral) transmission**.

### Other parameters
- **Incubation:** 2–21 days, often modeled as gamma/lognormal, mean ~9–11 days.
- **Serial interval:** ~**15 days** (commonly ~12–16) for West Africa.
- **Time death→burial:** often set to **~2 days** in ABMs (window of funeral transmission).
- **Relative infectivity of dead bodies (ε):** a key tunable parameter; funerals can contribute a large fraction of R0.

### Model families
- **Compartmental:** SEIR → extended to **SEIRD** (adds Dead/unburied) or **SEIHRD** (adds Hospitalized) to separate **community / hospital / funeral** transmission settings. Fitted via least-squares or MCMC.
- **Nonlinear incidence for behavior:** e.g., **Ricker-type exponential** λ = β(1−p)(I+εD)·exp(−(I+εD)/K), where **p** = behavior-change efficacy, **K** = speed of behavior change, **ε** = dead infectivity. Behavior change substantially reduces outbreak size/duration.
- **Agent-based models (ABM):** explicitly represent individuals, households, hospitals, funerals, and **social network links** (e.g., cut a dead agent's long-range links so only close kin/community get exposed at the funeral). NetLogo is an established, accessible platform for exactly this. Notable: Siettos/Russo-style ABMs, Merler et al., and the PLOS Currents 2014 Liberia/Sierra Leone ABM.

### Existing Ebola ABM / NetLogo work (starting points)
- **PLOS Currents Outbreaks (2015):** "Modeling the 2014 Ebola Virus Epidemic – Agent-Based Simulations … Liberia and Sierra Leone."
- **PLOS One (2018):** "An open-data-driven agent-based model to simulate infectious disease outbreaks."
- **"Modeling Post-death Transmission of Ebola"** (PMC4348651) — funeral transmission inference/control.
- **"Modelling the Role of Human Behaviour in EVD Transmission Dynamics"** (PMC9122724) — SIRD + behavior incidence.

---

## 6. Human Behavior Dimensions (the project's core)

These are where an ABM beats a pure compartmental model, and where the WHO platform needs the most help:

1. **Funeral & burial practices** — washing/touching the body; a major transmission route. Intervention: **Safe & Dignified Burials**. Model as a discrete high-risk contact event tied to each death, with compliance probability.
2. **Community trust & resistance** — distrust of authorities/foreigners → treatment-center fires, **150+ patient escapes**, attacks on burial/vaccination teams (seen in DRC 2018–20 and 2026). Model as trust state modulating compliance and care-seeking.
3. **Healthcare-seeking behavior** — delay or refusal to seek care → more community/household transmission + worse survival. Drives the split between community vs hospital transmission.
4. **Mobility & migration** — population movement, cross-border trade, dense/insecure regions spread the virus (explicit 2026 challenge). Model via agent movement / metapopulation links.
5. **Misinformation & rumor** — worsens outbreaks by reducing compliance and care-seeking (studied across diseases). Model as an information/belief layer affecting behavior.
6. **Compliance with interventions** — uptake of vaccination, isolation, IPC, safe burial. Behavior-change efficacy (p) and speed (K) are among the most influential parameters on R0 and final size.

**Design implication:** give each agent a behavioral/belief state (trust, fear, awareness, compliance) that updates from local events (deaths nearby, messaging, interventions) and gates their actions (attend funeral? seek care? accept vaccine?). This is the natural fit for **NetLogo + (optionally) an LLM giving agents richer, personality-driven decisions** — the differentiator for this project.

---

## Sources
- WHO Ebola fact sheet — https://www.who.int/news-room/fact-sheets/detail/ebola-virus-disease
- WHO Ebola outbreak DRC 2026 — https://www.who.int/emergencies/situations/ebola-outbreak---drc-2026
- WHO AFRO Ebola — https://www.afro.who.int/health-topics/ebola-disease
- WHO Ebola vaccine stockpiles / ICG — https://www.who.int/groups/icg/ebola-virus-disease/ebola-stockpiles
- CDC History of Ebola Outbreaks — https://www.cdc.gov/ebola/outbreaks/index.html
- CDC Ebola Current Situation — https://www.cdc.gov/ebola/situation-summary/index.html
- ECDC factsheet — https://www.ecdc.europa.eu/en/infectious-disease-topics/ebola-disease/disease-information/factsheet-about-ebola-disease
- Wikipedia: 2026 Central Africa Ebola epidemic — https://en.wikipedia.org/wiki/2026_Central_Africa_Ebola_epidemic
- Wikipedia: Western African Ebola epidemic — https://en.wikipedia.org/wiki/Western_African_Ebola_epidemic
- Wikipedia: Kivu Ebola epidemic — https://en.wikipedia.org/wiki/Kivu_Ebola_epidemic
- CIDRAP (case-count revision) — https://www.cidrap.umn.edu/ebola/who-drastically-downsizes-ebola-case-count-dr-congo-outbreak
- CDC EID: Transmission Models of Historical Ebola Outbreaks — https://wwwnc.cdc.gov/eid/article/21/8/14-1613_article
- Estimating R0 of EBOV 2014 West Africa — https://pmc.ncbi.nlm.nih.gov/articles/PMC4169395/
- ABM (PLOS Currents 2015, Liberia/Sierra Leone) — https://currents.plos.org/outbreaks/article/modeling-the-2014-ebola-virus-epidemic-agent-based-simulations-temporal-analysis-and-future-predictions-for-liberia-and-sierra-leone/
- Open-data-driven ABM (PLOS One 2018) — https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0208775
- Modeling Post-death Transmission of Ebola — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4348651/
- Modelling the Role of Human Behaviour in EVD — https://pmc.ncbi.nlm.nih.gov/articles/PMC9122724/
- WHO R&D efforts 2014–16 / Blueprint — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5524177/
- Inmazeb/Ebanga & PALM trial; Ervebo ring vaccination Guinea — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5700805/
