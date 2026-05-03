# NetLogo 6 → 7 Transition Notes (for AI clients porting old models)

This is a focused checklist for AI clients that load NetLogo models from
older sources — typically CoMSES Net archives — and find that the code
needs minor updates to run cleanly under NetLogo 7.0.x. It is **not** a
full language reference; for that, point the model author at
`netlogo://docs/primitives` and `netlogo://docs/programming`.

The single most important thing to know: **NetLogo 7 opens 6.x `.nlogo`
files automatically** and converts them to the new `.nlogox` (XML) format
on save. Most pre-7 models will run on first try. When they don't, the
fixes are short and mechanical — see below.

## When to use this guide

Look at this resource the moment you load a model from CoMSES (or any
pre-2025 source) and either:

- The compiler errors with a confusing message about a primitive, OR
- A run errors at a specific step that uses an idiom that changed.

Do **not** rewrite working code "to modernize it." Old idioms that still
compile are still correct.

---

## 1. File format: `.nlogo` vs `.nlogox`

| Concern | Answer |
|---|---|
| Will a 6.x `.nlogo` file open in NetLogo 7? | **Yes**, automatically. |
| Will a `.nlogox` open in NetLogo 6? | **No** — XML format is 7-only. |
| Should I rewrite the file format? | **No**. Just open it. NetLogo upgrades on save. |
| Will widgets resize? | NetLogo prompts; default is "resize and reposition." Either choice is fine; the model itself runs the same. |

When generating *new* models, prefer `.nlogox`. When loading *old* models,
leave them as `.nlogo` and let NetLogo handle it.

## 2. The handful of breaking language changes

These are the only fixes you'll typically need:

### 2.1 `task` → anonymous procedures (since 6.0)

```netlogo
;; OLD (5.x — auto-converted, but still seen in pre-2016 models):
let f task [ x -> x * 2 ]

;; NEW (6.0+):
let f [ [x] -> x * 2 ]
```

The `task` primitive is gone. The bracketed `-> body` form replaces it.
Question-mark variables (`?`, `?1`, `?2`) are no longer special — they
are ordinary names.

### 2.2 `ifelse-value` precedence (since 7.0)

`ifelse-value` now binds *less* tightly than infix operators, so old
expressions that mixed it with `+`, `-`, etc. need explicit parens:

```netlogo
;; OLD (6.x):
print ifelse-value (x > 5) [10] [3] + 2
;; means:  ifelse-value (x > 5) [10] [3 + 2]   (the old way)

;; NEW (7.0+):
print (ifelse-value (x > 5) [10] [3]) + 2
```

Symptom: a model that used to print `12` now prints `5` (or vice versa).
Add parens around every `ifelse-value` whose result is used in arithmetic.

### 2.3 Movie primitives → `vid` extension (since 6.0)

```netlogo
;; OLD:
movie-start "out.mov"
movie-grab-view
movie-close

;; NEW:
extensions [vid]
vid:start-recorder
vid:record-view
vid:save-recording "out.mov"
```

Symptom: "movie-start is not a known primitive."

### 2.4 Link reporters changed (since 6.0)

In 6.0, link reporters that did *not* specify a direction started
returning **all** links (directed + undirected). Reporters with `out` or
`in` started including undirected links too. Old code that assumed
"directed only" may now over-report.

If a model uses `link-neighbors`, `out-link-neighbors`, etc., and the
results look off, check whether the original model expected
directed-only behavior and add `with [is-directed-link? self]` filters
where needed. This is rare in practice — most models are explicit.

## 3. Things that did NOT change

Don't "fix" these — they still work:

- `ask`, `of`, `with`, `breeds`, `ticks`, `reset-ticks`
- `run`, `runresult` (the dynamic-call primitives — no rename)
- `random-seed`, `random-float`, `random-poisson`, etc.
- The `bf:` (`bitmap`), `csv:`, `nw:` (`network`), `gis:`, `table:` extensions — all bundled and stable
- BehaviorSpace experiment XML format inside `.nlogox` files
- The CSV table output format (still: 6 metadata rows + header + data)

## 4. Bundled extensions in NetLogo 7.0.3

Confirmed bundled in a default install: `arduino`, `array`, `bitmap`,
`csv`, `gis`, `gogo`, `ls`, `matrix`, `nw`, `palette`, `profiler`, `py`,
`resource`, `rnd`, `sample`, `sample-scala`, `sound`, `sr`, `table`,
`time`, `vid`, `view2.5d`.

**NOT bundled** (separate install required):

- `bspace` — the BehaviorSpace-as-NetLogo-code extension. The MCP server's
  `run_experiment` tool does *not* depend on this; it drives the headless
  launcher directly. If a model uses `extensions [bspace]`, you'll need
  to install the extension manually (github.com/NetLogo/BehaviorSpace-Extension).
- Most third-party extensions referenced in older CoMSES models (e.g.
  custom Java extensions). If a model errors with "extension not found,"
  ask the user — do not silently delete the `extensions [...]` line.

## 5. Common porting recipes

**Symptom:** "Nothing named X has been defined."
- Check sections 2.1–2.3 for renames.
- Check the model's `extensions [...]` line — it may need a manual
  install (see §4).

**Symptom:** "Expected a closing bracket here."
- Almost always section 2.1 (old `task` syntax). Look for `task [`.

**Symptom:** Numbers off by a factor or sign.
- Check section 2.2 (`ifelse-value` precedence).

**Symptom:** "movie-start" / similar movie command undefined.
- Section 2.3 (`vid` extension).

**Symptom:** Setup procedure errors on a primitive that *should* exist.
- Check whether the model expects an extension that isn't in §4's
  bundled list.

## 6. What to do when a fix isn't obvious

Don't guess. Ask the user:

> The model uses `<exact line>` which doesn't compile under NetLogo 7.
> This usually means [hypothesis from the patterns above]. Should I
> [proposed fix]? Or do you want to look at the original source first?

Always show the user the exact line you're about to change and the
exact replacement. NetLogo code is short — pasting both is cheap and
keeps the user in the loop.

---

References:
- NetLogo 7.0.3 transition page: https://docs.netlogo.org/7.0.3/transition
- NetLogo 7.0.0 changes overview: https://docs.netlogo.org/7.0.3/netlogo7intro
- BehaviorSpace docs: https://docs.netlogo.org/7.0.3/behaviorspace
