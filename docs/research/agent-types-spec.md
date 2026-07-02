# Agent Types — Proposed Specification (Mongbwalu / Bunia Ebola ABM)

*My module for the WHO/ASSOCC-Ebola project. Synthesised from the agent-typology research base (ChatGPT deep research, sources: IOM/DTM, Flowminder, Rift Valley Institute, IPIS, IKV Pax Christi mining study, ASSOCC, Covasim, Ebola ABM literature). 2026-06-23.*

## Design principle: layered, not flat
An "agent type" is **not one label**. Each person carries:
**base demographics** + **one livelihood role** + **one household context** + **overlays** (displacement, influence, security). This matches both Ituri's real complexity and standard epidemic-ABM practice (ASSOCC, Covasim separate age / household / work-school / mobility / contact-setting layers). Ethnicity and SES **modulate** where agents live, whom they trust, where they work, and how they react — they are not separate "ABM universes".

## Calibration numbers worth hard-coding (with the caveat they're estimates)
| Quantity | Value | Note |
|---|---|---|
| Ituri population | ~7.0 M | province context only |
| Bunia (wider urban) | ~1.5 M | agglomeration, not census |
| Mongbwalu town | **~50 k (2008 census-era)**; some media say up to ~130 k | Wikipedia/RVI give ~50k (2008); treat higher figures as a sensitivity scenario, not fact |
| Age 0–14 share | **46%** (national) | DRC very young; use as proxy |
| Mean household size | **5.3** (DHS 2023–24) | oversize host HH, densify IDP sites |
| IDPs in Ituri | ~900 k (~13%) | **82% in host communities, not camps** |
| Artisanal miners (province) | 60k–150k; ~5 dependents each | huge in Mongbwalu/Kilo corridor |
| Under-20 share of miners | ~20% | justifies adolescent-worker agents |
| Preschool (3–5) attendance | **5%** | do NOT assume "child = student" |
| Mongbwalu ↔ Bunia | **~48–85 km (sources vary; ~60 km by road on Wikipedia)** | key mobility/governance artery — confirm exact road distance |

## Core person-level attributes (the schema)
| Attribute | Values |
|---|---|
| Age band | 0–4, 5–11, 12–17, 18–29, 30–49, 50+ |
| Sex | F, M |
| Household form | nuclear, extended/multigenerational, single migrant, host household, site household |
| Residence zone | Bunia urban, Bunia peri-urban/Rwampara, Mongbwalu mining town, rural village/chiefdom, IDP site |
| Ethno-linguistic | Hema, Lendu/Ngiti, Alur, Bira/Banyali/Nyali, Lugbara/Nande/non-originaire, Other |
| Language set | Swahili (widest reach), local language, Lingala, French (elite/educated only) |
| Displacement | none, hosted IDP, site-based IDP, returnee |
| SES tier | better-off/elite, intermediate/precarious, poor/very poor |
| Main role | (see roles below) |
| Influence flag | none, customary leader, religious leader, teacher, health worker, trader hub, militia-linked, survivor/witness |
| Trust profile | continuous scores: kin, customary authority, religious authority, health workers, NGO/international, government/security |
| Mobility profile | home-centred, school-centred, farm-centred, mine-centred, market-centred, corridor trader, site-constrained |

## Main role classes (keep tractable; ~16, most are small)
Large: **dependent child**, **student child**, **adolescent mixed-role youth**, **smallholder farmer**, **artisanal miner**, **mining support labour** (crushers, washers, porters, cooks, vendors — many women & adolescents), **petty trader**.
Small but high-centrality: **trader/négociant/financer**, **transport worker** (boda-boda — share unknown, validate), **teacher**, **health worker**, **religious leader**, **customary/civil authority**, **armed/security actor**.
Overlays (not separate roles): **hosted IDP adult**, **site-based IDP adult**.

Zone weighting: Bunia → more trade/service/IDP; Mongbwalu/Kilo → more mining + support; rural Djugu/Irumu → more farming.

## Three-tier SES (defensible level of abstraction)
- **Elite:** controls pits/pumps/crushers/transport/gold-buying capital or formal authority; can seek care in Uganda/Kenya; better French. → big traders, quarry CEOs, financiers, chiefs, senior staff, some clergy.
- **Intermediate:** some regular income/role but liquidity-constrained. → teachers, nurses, shopkeepers, skilled transporters, small pit leaders.
- **Poor/very poor:** irregular cash, debt, displacement strain. → diggers, crushers, porters, casual labour, displaced farmers, female site service workers, many hosted IDPs.
> SES tracks **asset control + role in the mining/trade chain + displacement** more than ethnicity. Ethnicity drives **authority, grievance, trust pathways** (Hema/Lendu cleavage), but the mining workforce is multi-ethnic.

## Children rule (important, evidence-based)
- **<12:** mostly dependents, but mobile (compound, water points, school, church, funerals).
- **12–17:** split probabilistically between student / student-worker / domestic-care / petty trader / mine-support.
- **16–17 in mining zones:** sometimes economically active workers — especially poor/displaced/debt-burdened/mine-adjacent households.

## What the information/trust module (Serge) needs from each agent
Ethno-linguistic identity · preferred message **language** (Swahili wide, French narrow) · religious-network membership · customary-authority linkage · displacement status · SES · occupation · **influence flag** (influencers get larger broadcast radius + stronger persuasion) · **multi-dimensional trust scores** (not a single "trusts government" bit). → My agent types must carry these so his module plugs in.

## Contact settings to expose (for the disease side)
households · mine shafts/pit teams · crushing/processing workshops · food-&-water service areas around mines · markets (market-day rhythm) · churches/mosques · schools · health facilities · roadside transport nodes · checkpoints/roadblocks · IDP sites · **funerals** (Ebola super-spreader: one Sierra Leone funeral → 28 cases, 75% touched the corpse).

## Mobility (Flowminder, this outbreak)
Not closed: needs an **export layer**. Flows mostly stay in Ituri, concentrated along corridors (top recipient zones Lita 22%, Nizi, Bambu, Kilo, Nyankunde), with ~1% to Beni/Butembo. **Separate physical mobility from message mobility** (a miner returns weekly, but a rumour can move faster/slower via radio, church, traders; in poor-coverage areas info takes 2–3 days).

## NetLogo implementation recipe
1. Generate households (mean ~5.3; oversize host, densify sites).
2. ~Half the population in child/adolescent bands.
3. Set residence zone first.
4. Assign livelihood by zone.
5. Overlay displacement on top of livelihood.
6. Give a small fraction explicit influence roles.
7. Expose the contact settings above.

→ Maps onto the prototype's `people/ages.nls`, `people/classes.nls`, `people_management.nls`, `social_networks.nls`, `setup/household-configuration.nls`.

## Open questions for ground experts (highest value)
- Mongbwalu town / health-area **population**.
- Bunia & Rwampara **household-size distributions**.
- Share of **adolescents in mine-support labour**.
- Local estimate of **boda-boda / transport workers**.
- **Site-based vs hosted IDP** split around Bunia, mid-2026.
- Which **religious/customary leaders** are trusted by which communities.
- Is **Hema/Lendu** still the strongest trust cleavage, or do mine-network / displacement / church affiliation now matter more?

## ⚠️ Note on the source report
The research is strong and the **named sources are real and findable** (IOM, Flowminder, RVI, IPIS, IKV Pax Christi, ASSOCC, Covasim). But the inline `citeturn…` tokens are ChatGPT's internal citation placeholders — **not clickable links**. Before sharing externally, rely on the named **Selected source list**, not the tokens.

## Thinnest evidence (treat as local calibration params, not constants)
District literacy · Ituri religious percentages · current Mongbwalu population · occupational shares for boda-boda/teachers/health workers · formal daycare prevalence.

## Sources (verified — real, clickable)
*Cross-checked 2026-06-23 against primary sources. Use THESE links, not the `citeturn…` tokens from the raw research dump.*

**Demography & households**
- DRC DHS 2023–24 (Key Indicators) — https://dhsprogram.com/publications/publication-pr156-preliminary-reports-key-indicators-reports.cfm · record: https://ghdx.healthdata.org/record/democratic-republic-congo-demographic-and-health-survey-2023-2024
- DRC demographics (0–14 ≈ 46%) — https://en.wikipedia.org/wiki/Demographics_of_the_Democratic_Republic_of_the_Congo · https://www.worldometers.info/demographics/democratic-republic-of-the-congo-demographics/

**Ethnicity, mining & political economy (Ituri)**
- Rift Valley Institute, *Gold, Land and Ethnicity in North-Eastern Congo* (Usalama Project) — https://riftvalley.net/wp-content/uploads/2018/06/RVI-Usalama-Project-4-Ituri.pdf
- IKV Pax Christi / Haki na Amani, *A Golden Future in Ituri?* (mining roles, ages, traders) — http://www.bibalex.org/search4dev/files/434680/464185.pdf
- HRW, *The Curse of Gold* (DRC gold/Mongbwalu) — https://www.hrw.org/report/2005/06/01/curse-gold
- Mongbwalu (town profile, ~50k as of 2008, ~60 km road to Bunia) — https://en.wikipedia.org/wiki/Mongbwalu

**Displacement**
- IOM DTM Ituri Mobility Tracking, Round 13 (903,282 IDPs = 13%) — https://dtm.iom.int/sites/g/files/tmzbdl1461/files/reports/MT_REPORT_ITURI_2025_EN_FINAL.pdf
- IOM DTM DRC Internal Displacement Overview 2026 — https://dtm.iom.int/reports/drc-internal-displacement-overview-2026

**Education (children/students)**
- UNICEF DRC Education (preschool 3–5 ≈ 5%; 7.6M out of school) — https://www.unicef.org/drcongo/en/what-we-do/education
- UNICEF: 130k+ additional children out of school in Ituri — https://www.unicef.org/drcongo/en/press-releases/over-130000-additional-children-out-school-ituri-province-violence

**Funeral transmission**
- CDC MMWR, *Cluster of Ebola Linked to a Single Funeral — Moyamba, Sierra Leone, 2014* (28 cases; 75% touched corpse) — https://www.cdc.gov/mmwr/volumes/65/wr/mm6508a2.htm

**ABM method (ASSOCC)**
- *The ASSOCC Simulation Model* (4 agent types; households; Dignum, Umeå) — https://rofasss.org/2020/04/25/the-assocc-simulation-model/ · conceptual model: https://simassocc.wordpress.com/wp-content/uploads/2020/06/conceptual-model-assocc.pdf

**2026 outbreak context (named real sources; %s not line-verified)**
- SSHAP, *Ituri Ebola Outbreak 2026 — context overview* — https://www.socialscienceinaction.org/resources/ituri-ebola-outbreak-2026-drc-summary-overview-of-context/

### Fact-check log
- ✅ Verified exact: 0–14=46%; Ituri ethnicity shares (RVI); IDPs 903,282/13%; preschool 5%; 7.6M out of school; Sierra Leone funeral 28 cases/75%; ASSOCC 4 types.
- ⚠️ Corrected: Mongbwalu↔Bunia "85 km" → ~48–85 km (≈60 km road); Mongbwalu pop "130k" → ~50k (2008), 130k weak.
- 🟡 Plausible, single-source (use but don't overstate): household size 5.3; miners 60k–150k; 82% IDPs in host communities; faith 60% education / 40% health; 2026 Flowminder corridor percentages.
