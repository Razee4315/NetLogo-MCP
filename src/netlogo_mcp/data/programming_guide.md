# NetLogo Programming Guide (6.4)

A reference for generating correct NetLogo code. Covers syntax, semantics, common patterns, and pitfalls.

---

## 1. Model Structure

### The .nlogo File

A `.nlogo` file is a plain-text file with sections delimited by the `@#$#@#$#@` separator. The key sections in order are:

1. **Code tab** — All procedures and declarations (the source code).
2. **Interface tab** — Widget definitions (buttons, sliders, monitors, plots, switches, choosers, inputs, outputs).
3. **Info tab** — Documentation in Markdown.
4. **Additional sections** — Shape definitions, BehaviorSpace experiments, preview commands, and other metadata.

When generating a model programmatically, you must produce **at minimum** the code section and the interface widget definitions separated by `@#$#@#$#@`.

### Procedures

All code lives inside procedures. There are two kinds:

```netlogo
;; Command procedure (does something, returns nothing)
to do-something
  ;; body
end

;; Reporter procedure (computes and returns a value)
to-report compute-something
  report 42
end
```

- `to` begins a command procedure; `to-report` begins a reporter procedure.
- `end` closes both kinds.
- Procedures can take arguments: `to move-forward [dist]` / `to-report add [a b]`.
- Procedure names are case-insensitive. `Setup`, `setup`, and `SETUP` all refer to the same procedure.

### Setup and Go

By convention, NetLogo models have two core procedures:

```netlogo
to setup
  clear-all          ;; reset everything
  ;; create agents, initialize variables
  reset-ticks        ;; initialize the tick counter to 0
end

to go
  ;; agent behavior per step
  tick               ;; advance the tick counter by 1
end
```

- `setup` is typically wired to a "Setup" button (once).
- `go` is typically wired to a "Go" button (forever/continuous).
- `reset-ticks` must be the **last** line of `setup`. It triggers plot updates.
- `tick` must be the **last** line of `go`. It triggers plot updates.

### Observer / Turtles / Patches / Links

NetLogo has four agent types:

| Agent Type | Description |
|---|---|
| **Observer** | The top-level agent. Runs `setup`, `go`, and any code not inside `ask`. There is exactly one observer. |
| **Turtles** | Mobile agents on the grid. Have heading, position (xcor, ycor), color, shape, etc. |
| **Patches** | Stationary grid cells. Have pxcor, pycor, pcolor, plabel. Cannot move. |
| **Links** | Connections between two turtles. Have end1, end2, color, thickness. |

Procedure code at the top level runs in **observer context**. Use `ask` to switch into agent context.

---

## 2. Agent Contexts

### Context Rules

Every command and reporter belongs to one or more contexts. Running a command in the wrong context is a runtime error.

| Context | Who is "self" | Can use |
|---|---|---|
| Observer | The observer | `turtles`, `patches`, `links`, global variables, `ask` |
| Turtle | A specific turtle | `xcor`, `ycor`, `heading`, `forward`, `patch-here`, turtle variables |
| Patch | A specific patch | `pxcor`, `pycor`, `pcolor`, `neighbors`, patch variables |
| Link | A specific link | `end1`, `end2`, `link-length`, link variables |

### Switching Context with `ask`

```netlogo
;; Observer context
ask turtles [
  ;; Now in turtle context — "self" is each turtle in turn
  forward 1
]

ask patches [
  ;; Now in patch context
  set pcolor green
]

ask links [
  ;; Now in link context
  set color red
]
```

`ask` iterates over the agentset in a **random order** each time it is called.

You can also ask a single agent:

```netlogo
ask turtle 0 [ set color red ]
ask patch 0 0 [ set pcolor blue ]
```

### Nested ask

```netlogo
ask turtles [
  ;; turtle context
  ask patch-here [
    ;; now in patch context — "myself" refers to the calling turtle
    set pcolor [color] of myself
  ]
]
```

- `myself` — refers to the agent that invoked the current `ask`.
- `self` — refers to the agent currently running code.

### Common Context Errors

```netlogo
;; ERROR: forward is turtle-only; cannot call from observer context
forward 1

;; FIX:
ask turtles [ forward 1 ]

;; ERROR: pcolor is patch-only; cannot call from observer context
set pcolor red

;; FIX:
ask patches [ set pcolor red ]

;; ERROR: cannot use create-turtles inside turtle context
ask turtles [ create-turtles 1 ]

;; FIX: use hatch instead, or move create-turtles to observer context
ask turtles [ hatch 1 ]
```

Key rule: **`create-turtles` (and `create-<breed>`) is observer-only.** Inside turtle context, use `hatch` or `sprout` (from patch context).

---

## 3. Breeds

### Declaring Breeds

Breeds are declared at the top of the code tab, before any procedures:

```netlogo
breed [wolves wolf]
breed [sheep a-sheep]
```

- The first name is the **plural** (agentset name): `wolves`, `sheep`.
- The second name is the **singular** (used for single-agent reporters): `wolf 0`, `a-sheep 3`.
- All breed members are also turtles. `turtles` includes all breeds.

### Breed-Specific Variables

```netlogo
wolves-own [energy pack-id]
sheep-own [wool-length]
```

These variables exist only on agents of that breed. Accessing a wolf-only variable on a sheep is a runtime error.

### Creating Breed Members

```netlogo
;; Observer context only
create-wolves 10 [
  set energy 100
  set color gray
  setxy random-xcor random-ycor
]

create-sheep 20 [
  set wool-length 0
  set color white
  setxy random-xcor random-ycor
]
```

### Breed-Specific Agentsets

```netlogo
ask wolves [ ... ]           ;; ask all wolves
ask sheep [ ... ]            ;; ask all sheep

count wolves                 ;; number of wolves
any? sheep                   ;; are there any sheep?

wolves with [energy < 10]    ;; wolves whose energy is low
```

### Checking and Changing Breed

```netlogo
;; Check breed
if breed = wolves [ ... ]
;; or equivalently
if is-wolf? self [ ... ]

;; Change breed (resets breed-specific variables)
set breed sheep
```

---

## 4. Variables

### Global Variables

Declared at the top of the code tab or created automatically by interface widgets (sliders, switches, choosers, inputs):

```netlogo
globals [total-energy num-alive]
```

Accessible from **any** context. Set with `set`:

```netlogo
set total-energy 0
```

A slider named `population-size` on the interface automatically creates a global variable `population-size`. Do **not** redeclare it in `globals`.

### Agent Variables

```netlogo
turtles-own [energy speed]
patches-own [fertility moisture]
links-own [strength]
```

Each agent gets its own copy. Set inside the appropriate context:

```netlogo
ask turtles [ set energy 100 ]
ask patches [ set fertility random-float 1.0 ]
```

### Built-in Agent Variables

Turtles have built-in variables: `who`, `color`, `heading`, `xcor`, `ycor`, `shape`, `label`, `label-color`, `breed`, `hidden?`, `size`, `pen-size`, `pen-mode`.

Patches have: `pxcor`, `pycor`, `pcolor`, `plabel`, `plabel-color`.

Links have: `end1`, `end2`, `color`, `label`, `label-color`, `hidden?`, `breed`, `thickness`, `shape`, `tie-mode`.

### Local Variables

Use `let` to create a local variable within a procedure or block:

```netlogo
to do-something
  let best-patch max-one-of neighbors [fertility]
  face best-patch
  forward 1
end
```

- `let` declares and initializes: `let x 5`
- `set` reassigns: `set x 10`
- Scope: the enclosing `[ ]` block or procedure.

### Reading Agent Variables from Another Context

Use `of`:

```netlogo
;; From observer context, read a turtle's energy
let e [energy] of turtle 0

;; Get a list of all turtle energies
let energies [energy] of turtles

;; Read a patch variable
let f [fertility] of patch 3 4
```

---

## 5. Control Flow

### if / ifelse

```netlogo
if energy < 0 [
  die
]

ifelse energy > 50
  [ reproduce ]
  [ set color red ]
```

- `if` takes one block (the true branch).
- `ifelse` takes two blocks (true branch, then false branch).
- There is no `else if`. Nest `ifelse` inside the false branch:

```netlogo
ifelse energy > 100 [
  ;; high energy
] [
  ifelse energy > 50 [
    ;; medium energy
  ] [
    ;; low energy
  ]
]
```

**`ifelse-value`** is the expression form (returns a value):

```netlogo
let status ifelse-value (energy > 50) ["healthy"] ["weak"]
```

### while

```netlogo
while [count turtles < 100] [
  create-turtles 1
]
```

The condition is in `[ ]` brackets (it is a reporter block).

### repeat

```netlogo
repeat 10 [
  forward 1
  right random 60 - 30
]
```

Executes the block a fixed number of times.

### ask

Already covered above. Key points:

- `ask` is both context-switching and iteration.
- Random order each time.
- Cannot nest `ask` on the same agentset recursively in ways that modify it.

### foreach

Iterates over a list:

```netlogo
foreach [1 2 3 4 5] [ x ->
  show x
]

;; Multiple lists (must be same length)
(foreach [1 2 3] ["a" "b" "c"] [ [num letter] ->
  show (word num letter)
])
```

Note: Multi-list `foreach` requires parentheses around the entire expression.

### map

Transforms a list, returns a new list:

```netlogo
let doubled map [x -> x * 2] [1 2 3 4]
;; doubled = [2 4 6 8]
```

### filter

Selects list elements matching a condition:

```netlogo
let big-numbers filter [x -> x > 3] [1 2 3 4 5]
;; big-numbers = [4 5]
```

### reduce

Combines list elements into a single value:

```netlogo
let total reduce + [1 2 3 4 5]
;; total = 15

let product reduce [ [a b] -> a * b ] [1 2 3 4 5]
;; product = 120
```

### carefully / error-message

Exception handling:

```netlogo
carefully [
  ;; code that might error
  let result 1 / 0
] [
  ;; runs if an error occurred
  show (word "Error: " error-message)
]
```

### stop

Exits the current procedure (command procedures only):

```netlogo
to go
  if count turtles = 0 [ stop ]  ;; stop this procedure
  ask turtles [ move ]
  tick
end
```

When `stop` is used in a forever-button procedure, it stops the button.

### every

Throttles execution to at most once per time interval (in seconds):

```netlogo
every 0.5 [
  ;; runs at most every 0.5 seconds of wall-clock time
  update-display
]
```

---

## 6. Agentsets

### What is an Agentset?

An agentset is an unordered collection of agents. The built-in agentsets are `turtles`, `patches`, `links`, and any breed names.

Agentsets are **immutable snapshots** when created with `with` or similar reporters.

### Filtering with `with`

```netlogo
let hungry-wolves wolves with [energy < 20]
let green-patches patches with [pcolor = green]
let nearby turtles with [distance myself < 5]
```

`with` takes a **boolean reporter block** in `[ ]`.

### Agentset Reporters

| Reporter | Description |
|---|---|
| `count agentset` | Number of agents |
| `any? agentset` | True if non-empty |
| `one-of agentset` | Random agent from set |
| `n-of n agentset` | Random n agents (error if n > count) |
| `up-to-n-of n agentset` | Random up-to-n agents (safe) |
| `sort-on [reporter] agentset` | Sorted list of agents |
| `max-one-of agentset [reporter]` | Agent with highest value |
| `min-one-of agentset [reporter]` | Agent with lowest value |
| `max-n-of n agentset [reporter]` | Top n agents by value |
| `min-n-of n agentset [reporter]` | Bottom n agents by value |
| `member? agent agentset` | True if agent is in set |
| `with-min [reporter] agentset` | All agents tied for minimum (use `agentset with-min [reporter]`) |
| `with-max [reporter] agentset` | All agents tied for maximum (use `agentset with-max [reporter]`) |

### Building Custom Agentsets

```netlogo
;; Combine individual agents or agentsets
let my-set (turtle-set turtle 0 turtle 1 turtle 5)
let combined (turtle-set wolves sheep)

let my-patches (patch-set patch 0 0 patch 1 1 neighbors)
let my-links (link-set link 0 1 link 2 3)
```

These constructors accept any mix of individual agents, agentsets, and `nobody`.

### Agentsets Are Random-Order

```netlogo
;; Each ask iterates in a different random order
ask turtles [ forward 1 ]

;; To iterate in a deterministic order, convert to a sorted list
foreach sort-on [who] turtles [ t ->
  ask t [ forward 1 ]
]
```

### nobody

`nobody` is the null agent. It is **not** the same as an empty agentset.

```netlogo
let target one-of wolves
if target != nobody [
  face target
]

;; For agentsets, use any? to check emptiness
if any? wolves [ ... ]
```

---

## 7. Movement and Space

### Turtle Movement Commands

| Command | Description |
|---|---|
| `forward n` / `fd n` | Move forward n steps along heading |
| `back n` / `bk n` | Move backward n steps |
| `right n` / `rt n` | Turn right n degrees |
| `left n` / `lt n` | Turn left n degrees |
| `setxy x y` | Jump to coordinates (x, y) |
| `move-to agent` | Jump to agent's location |
| `face agent` | Set heading toward agent |
| `facexy x y` | Set heading toward (x, y) |

### Heading

- Heading is in degrees: 0 = north, 90 = east, 180 = south, 270 = west.
- `heading` is a turtle variable (0 to 359.999...).

### Wrapping vs. Bounded Worlds

By default, the world **wraps** both horizontally and vertically (toroidal topology).

Topology is configured in the interface (or via API). Four topologies:

| Topology | Wraps X | Wraps Y |
|---|---|---|
| Torus (default) | Yes | Yes |
| Cylinder (horizontal) | Yes | No |
| Cylinder (vertical) | No | Yes |
| Box | No | No |

In a bounded (non-wrapping) dimension, turtles cannot move past the edge. `forward` will produce a runtime error if a turtle tries to go past the boundary. To avoid this:

```netlogo
;; Check before moving
if can-move? 1 [ forward 1 ]
```

### Distance and Direction

```netlogo
distance other-agent         ;; distance from self to other agent
distancexy x y               ;; distance from self to (x, y)
towards other-agent          ;; heading from self toward other agent
towardsxy x y                ;; heading from self toward (x, y)
```

All distance/direction calculations respect world topology (wrapping).

### Patch Reporters

```netlogo
patch-here                   ;; the patch the turtle is on
patch-at dx dy               ;; patch at offset (dx, dy) from turtle
patch-ahead dist             ;; patch that is dist ahead along heading
neighbors                    ;; 8 surrounding patches (Moore neighborhood)
neighbors4                   ;; 4 surrounding patches (Von Neumann)
```

`neighbors` and `neighbors4` return agentsets. They respect topology — at a non-wrapping edge, they return fewer patches.

### Other Spatial Reporters

```netlogo
turtles-here                 ;; turtles on the same patch as self
turtles-on patch-or-agentset ;; turtles on given patch(es)
other turtles-here           ;; same as turtles-here minus self
in-radius dist               ;; agents within distance
in-cone dist angle           ;; agents within a cone (vision arc)

;; Example: wolves within 3 units
wolves in-radius 3

;; Example: sheep visible ahead within 90-degree cone at 5 units distance
sheep in-cone 5 90
```

---

## 8. Links

### Directed vs. Undirected Links

```netlogo
;; Undirected link breed
undirected-link-breed [friendships friendship]

;; Directed link breed
directed-link-breed [influences influence]
```

If you do not declare link breeds, you can use the default link commands, which create undirected links.

### Creating Links

```netlogo
;; From observer context:
ask turtle 0 [ create-link-with turtle 1 ]        ;; undirected
ask turtle 0 [ create-link-to turtle 1 ]           ;; directed (0 -> 1)
ask turtle 0 [ create-link-from turtle 1 ]         ;; directed (1 -> 0)

;; Create links with all members of an agentset
ask turtle 0 [ create-links-with other turtles ]

;; With breed
ask wolf 0 [ create-influence-to wolf 1 ]
ask wolf 0 [ create-friendship-with wolf 1 ]
```

Note: `create-link-with` / `create-link-to` / `create-link-from` are **turtle context** commands.

### Link Reporters

```netlogo
;; Getting links
[my-links] of turtle 0           ;; all links connected to turtle 0
[my-in-links] of turtle 0        ;; directed links pointing to turtle 0
[my-out-links] of turtle 0       ;; directed links pointing from turtle 0

;; Getting a specific link
link 0 1                          ;; the undirected link between turtle 0 and turtle 1
;; For directed links, order matters:
influence 0 1                     ;; directed link from 0 to 1

;; Link neighbors (turtles connected via links)
link-neighbors                    ;; undirected neighbors
in-link-neighbors                 ;; turtles with directed links pointing to self
out-link-neighbors                ;; turtles self points to
```

### Link Variables and Properties

```netlogo
links-own [strength]
influences-own [weight]

ask links [
  set color red
  set thickness 0.2
]

;; Link length
[link-length] of link 0 1
```

### Network Primitives (via NW Extension)

For advanced network analysis, use the `nw` extension:

```netlogo
extensions [nw]

;; In a procedure:
nw:set-context turtles links
let clustering nw:clustering-coefficient
let path nw:path-to turtle 5
let betweenness nw:betweenness-centrality
```

---

## 9. Common Patterns

### Setup Pattern

```netlogo
globals [grass-total]

breed [wolves wolf]
breed [sheep a-sheep]

wolves-own [energy]
sheep-own [energy]

patches-own [grass]

to setup
  clear-all                        ;; reset everything

  ;; Create and initialize patches
  ask patches [
    set grass random-float 10.0
    recolor-patch
  ]

  ;; Create agents
  create-wolves initial-wolves [    ;; initial-wolves is a slider
    set energy 50
    set color gray
    set shape "wolf"
    setxy random-xcor random-ycor
  ]

  create-sheep initial-sheep [
    set energy 30
    set color white
    set shape "sheep"
    setxy random-xcor random-ycor
  ]

  set grass-total sum [grass] of patches

  reset-ticks                       ;; MUST be last line
end
```

### Go Pattern

```netlogo
to go
  if not any? turtles [ stop ]     ;; stopping condition

  ask wolves [
    move
    eat-sheep
    reproduce-wolf
    set energy energy - 1
    if energy <= 0 [ die ]
  ]

  ask sheep [
    move
    eat-grass
    reproduce-sheep
    set energy energy - 1
    if energy <= 0 [ die ]
  ]

  ask patches [ grow-grass ]

  tick                              ;; MUST be last line
end
```

### Random Walk

```netlogo
to move  ;; turtle procedure
  right random 50
  left random 50
  forward 1
end
```

### Levy Flight (Variable Step Length)

```netlogo
to levy-walk  ;; turtle procedure
  right random 360
  let step-length (random-float 1) ^ (-1 / levy-exponent)
  forward step-length
end
```

### Diffusion

```netlogo
;; Built-in diffusion on a patch variable
diffuse chemical 0.5    ;; each patch shares 50% of chemical with neighbors (8)
diffuse4 chemical 0.5   ;; shares with 4 neighbors instead of 8
```

### Gradient Following

```netlogo
to follow-gradient  ;; turtle procedure
  let target max-one-of neighbors [chemical]
  if [chemical] of target > chemical-threshold [
    face target
    forward 1
  ]
end
```

### Reproduction by Hatching

```netlogo
to reproduce  ;; turtle procedure
  if energy > reproduction-threshold [
    set energy energy / 2
    hatch 1 [
      set energy [energy] of myself
      right random 360
      forward 1
    ]
  ]
end
```

### Interaction Between Agents

```netlogo
to eat-sheep  ;; wolf procedure
  let prey one-of sheep-here
  if prey != nobody [
    ask prey [ die ]
    set energy energy + energy-gain-from-sheep
  ]
end
```

### Using Tick-Based Timing

```netlogo
;; Do something every N ticks
to go
  if ticks mod 10 = 0 [
    regrow-resources
  ]
  ;; ...
  tick
end
```

### Plotting (in-code plot updates)

```netlogo
;; If plots use "update commands" in the interface, they auto-update on tick.
;; For manual plotting:
set-current-plot "Population"
set-current-plot-pen "wolves"
plot count wolves
set-current-plot-pen "sheep"
plot count sheep
```

---

## 10. Common Mistakes

### 1. Using `=` Instead of `set`

```netlogo
;; WRONG: = is comparison, not assignment
energy = 100

;; CORRECT:
set energy 100
```

`=` is a boolean reporter that returns `true` or `false`. Assignment is always done with `set`.

### 2. Forgetting `tick` / `reset-ticks`

```netlogo
;; WRONG: plots will not update, ticks will not advance
to setup
  clear-all
  create-turtles 10
  ;; missing reset-ticks
end

to go
  ask turtles [ forward 1 ]
  ;; missing tick
end

;; CORRECT:
to setup
  clear-all
  create-turtles 10
  reset-ticks
end

to go
  ask turtles [ forward 1 ]
  tick
end
```

### 3. Wrong Context Errors

```netlogo
;; WRONG: create-turtles is observer-only
ask turtles [
  create-turtles 1
]

;; CORRECT: use hatch in turtle context
ask turtles [
  hatch 1
]

;; WRONG: fd is turtle-only
fd 1

;; CORRECT:
ask turtles [ fd 1 ]

;; WRONG: using turtle variables in observer context without "of"
show energy

;; CORRECT:
show [energy] of turtle 0
```

### 4. Forgetting Brackets in Agentset Filters

```netlogo
;; WRONG: condition must be in brackets
turtles with energy > 5

;; CORRECT:
turtles with [energy > 5]
```

### 5. Using `report` vs `stop`

```netlogo
;; WRONG: using stop in a to-report procedure
to-report best-patch
  stop  ;; ERROR: reporter must use report, not stop

;; CORRECT:
to-report best-patch
  report max-one-of neighbors [fertility]
end

;; WRONG: using report in a to (command) procedure
to move
  report 5  ;; ERROR: command procedures cannot use report

;; CORRECT:
to move
  forward 5
end
```

### 6. Confusing `nobody` and Empty Agentset

```netlogo
;; one-of returns nobody when the agentset is empty
let target one-of turtles-here

;; WRONG: comparing agent to empty agentset
if target = [] [ ... ]

;; CORRECT:
if target = nobody [ ... ]

;; For agentsets, use any?
if not any? turtles-here [ ... ]
```

### 7. Variable Shadowing with `let`

```netlogo
;; WRONG: redeclaring a variable that already exists in scope
let x 5
let x 10  ;; ERROR: x already defined

;; CORRECT: use set to reassign
let x 5
set x 10
```

### 8. Math Pitfalls

```netlogo
;; Integer division does NOT truncate in NetLogo — it returns a float
show 5 / 2    ;; => 2.5 (not 2)

;; Use int, floor, ceiling, round for integer results
show int (5 / 2)     ;; => 2
show floor (5 / 2)   ;; => 2
show ceiling (5 / 2) ;; => 3

;; Modulo
show 7 mod 3   ;; => 1

;; Random numbers
random 10          ;; integer in [0, 9]
random-float 10.0  ;; float in [0, 10.0)
```

### 9. String Concatenation

```netlogo
;; WRONG: + does not work on strings
let msg "hello" + " world"

;; CORRECT: use word
let msg (word "hello" " world")
;; Parentheses are needed when word takes more than 2 arguments
let msg2 (word "x=" x " y=" y)
```

### 10. List Operations Are Not In-Place

```netlogo
;; WRONG: lput does not modify the list
let my-list [1 2 3]
lput 4 my-list        ;; returns [1 2 3 4] but my-list is unchanged

;; CORRECT:
let my-list [1 2 3]
set my-list lput 4 my-list   ;; now my-list = [1 2 3 4]
```

### 11. Parentheses for Variadic Primitives

Some primitives accept a variable number of arguments but require parentheses:

```netlogo
;; Default: two arguments, no parentheses needed
let s word "a" "b"

;; Variadic: more than default arguments, parentheses required
let s2 (word "a" "b" "c" "d")
let total (list 1 2 3 4 5)
let biggest (max (list a b c))
```

Primitives that commonly need this: `word`, `list`, `sentence`, `turtle-set`, `patch-set`, `link-set`, `foreach`, `map`.

### 12. Forgetting `other`

```netlogo
;; WRONG: includes self in the agentset
let nearby turtles in-radius 3
;; self is always within radius 0, so self is included

;; CORRECT: exclude self
let nearby other turtles in-radius 3
```

---

## Quick Reference: Operator Precedence

NetLogo does **not** have traditional operator precedence. Arithmetic follows standard math precedence (*, / before +, -), but logical operators do not chain as expected. Use parentheses liberally:

```netlogo
;; Ambiguous:
if x > 5 and y < 3 or z = 1 [ ... ]

;; Clear:
if (x > 5 and y < 3) or z = 1 [ ... ]
```

## Quick Reference: Useful Primitives

| Primitive | Description |
|---|---|
| `random-xcor` / `random-ycor` | Random coordinate within world bounds |
| `random-float x` | Random float in [0, x) |
| `random x` | Random integer in [0, x-1] |
| `one-of list-or-agentset` | Random element |
| `n-values n [i -> expr]` | Generate list of n values |
| `range start stop step` | Generate range list |
| `item n list` | Get nth element (0-indexed) |
| `length list` | List length |
| `but-first list` | All but first element |
| `but-last list` | All but last element |
| `fput val list` | Prepend to list |
| `lput val list` | Append to list |
| `sort list` | Sort ascending |
| `sort-by comp list` | Sort with comparator |
| `remove val list` | Remove all occurrences |
| `remove-duplicates list` | Remove duplicates |
| `position val list` | Index of val (or false) |
| `substring str start end` | Extract substring |
| `read-from-string str` | Parse string to value |
| `timer` / `reset-timer` | Wall-clock timing |
| `date-and-time` | Current date/time string |

---

## Quick Reference: Extensions

Common extensions loaded at the top of the code tab:

```netlogo
extensions [
  nw        ;; network analysis
  gis       ;; GIS data import
  csv       ;; CSV file reading/writing
  table     ;; hash table (dictionary) data structure
  array     ;; mutable array data structure
  matrix    ;; matrix math
  profiler  ;; performance profiling
  palette   ;; advanced color palettes
  bitmap    ;; image import
  vid       ;; video recording
  py        ;; Python integration
  r         ;; R integration
]
```

### Table Extension Example

```netlogo
extensions [table]

globals [lookup]

to setup
  clear-all
  set lookup table:make
  table:put lookup "alpha" 1
  table:put lookup "beta" 2
  show table:get lookup "alpha"   ;; => 1
  show table:has-key? lookup "gamma"  ;; => false
  reset-ticks
end
```

### CSV Extension Example

```netlogo
extensions [csv]

to load-data
  let rows csv:from-file "data.csv"
  ;; rows is a list of lists
  foreach rows [ row ->
    ;; process each row
    let name item 0 row
    let value item 1 row
  ]
end
```
