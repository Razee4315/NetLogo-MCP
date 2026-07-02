# Ebola Project — Meeting Notes & My Assignment (2026-06-23)

*First team meeting (Zoom). Attendees: Frank Dignum (lead, ASSOCC creator), Serge Stinckwich (UNU), Bertilla Fabris (cybertilla, prototype author), Emil Johansson (prototype contributor), JJ Majewski (Warsaw), Saqlain.*

---

## ⭐ MY ASSIGNMENT: Agent Types / Population

I am responsible for **agent types** — defining who the agents are, based on the old ASSOCC model and adapted for Ebola/Mongbwalu.

**What this means concretely:**
1. **Review the previous ASSOCC model's agent types** — it was simple: age-based (children / adults / retired).
2. **Design new, richer agent types for Ebola in Mongbwalu**, across several dimensions:
   - **Occupation / role:** miners (artisanal), traders, caregivers, health workers, farmers, **priests / religious leaders**, militia, etc.
   - **Ethnicity:** Lendu / Hema (and others) — different groups, different authority figures, possibly different towns/areas.
   - **Socio-economic status (SES):** elites / moderate / poor.
   - **Age:** children, adults, retired — BUT note the suggestion that **child age may not matter much; children might be modelled as workers** (in mining context).
   - **Displacement status** (IDPs / displacement camps).
3. **Map agent types → activities** (which agents do what: football, church, market, mining, school/daycare, funerals).
4. Look at the **module documentation** they have for how agents are structured.

**Repo to work in:** `github.com/cybertilla/ebolaTest` (Bertilla's prototype, fork of ASSOCC).

---

## Decisions / themes from the meeting

- **Information flow → Serge** owns this strand.
- **Misinformation** is central: how it spreads/separates, how beliefs form, how people *act* on belief. When correct info is unavailable → misinformation fills the gap → people turn to **local/traditional medicine**.
- **Key behaviour to capture:** people **not going to hospitals and dying at home**.
- **Agents → actions** is the core loop (agents choose actions based on type/needs).
- **Activities matter:** football, church, market, mining, school/daycare — these are gathering/transmission points.
- **Children:** at home or daycare (and possibly treated as workers — open question).
- **Map:** a **simplified map / area** based on Google Maps so the model has a sense of **distance** (e.g. how far the hospital is). Different ethnic groups may live in different towns/areas.
- **Transmission note:** Ebola is **not as contagious as COVID** — it's close-contact, so the contact model differs.
- **Use the previous (ASSOCC) model** as the base — review its structure and agent types.

---

## Open questions for ground experts (JJ Majewski's list + Questions.docx)
Keep a running list of what to ask people on the ground:
1. When do people call the authorities (re: symptoms, or proportion of sick in a household/community)?
2. Who are the authority figures, how many, who listens to them, on what matters?
3. Size of contact network vs dwelling/settlement size (small vs large village/city)?
4. The "range" of the spatially-constrained word-of-mouth network — how far does an average person travel per day/week (= furthest the information can come from)?
5. How many people have internet access in the region — what does it depend on?
6. How many have TV/radio access — what does it depend on?
7. How far does an average person travel for business?
8. Is there a census of displacement camps; if so, their composition?
9. Typical responses to authorities — relationship with actor characteristics (ethnicity, SES, occupation, age, gender, community role)?
(+ see `Questions.docx` in the Drive for the team's existing question list.)

---

## My to-do (after finals)
- [ ] Read the **previous ASSOCC model**'s agent/population code (`people/ages.nls`, `people/classes.nls`, `people_management.nls`, `social_networks.nls`, `setup/household-configuration.nls`).
- [ ] Read the **module documentation** in the Drive (how agents are defined).
- [ ] Draft a **table of new agent types** × dimensions (occupation, ethnicity, SES, age, displacement, community role) → mapped to activities/gathering points.
- [ ] Note which attributes the **information-flow strand (Serge)** needs from agents (trust, ethnic/religious group, role) so my agent types support his module.
- [ ] Bring the draft to the next meeting / share with Frank & Bertilla.

## Useful (already done, in my back pocket)
- I already studied the Mongbwalu demographics (Lendu ~60% / Hema ~25%, miners 40–50%, ~6-person households) — see [[Ebola Project Repo Analysis]] / `docs/research/`.
- My standalone model already implements occupations + ethnicity + households + a social network — reusable as a reference for the agent-types design.

---
*Note: my own NetLogo information/trust model and experiments stay in my back pocket for now — the team assigned me agent types, and Serge owns information flow. Align my agent-types work to support his module.*
