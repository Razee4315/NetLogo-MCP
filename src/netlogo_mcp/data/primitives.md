# NetLogo 6.4 Primitives Quick Reference

A curated reference of commonly used NetLogo primitives organized by category.
Syntax conventions: `agentset` = a set of agents, `agent` = a single agent, `n` = number, `expr` = expression, `block` = command block in brackets.

---

## 1. Turtle Commands

`create-turtles n [block]` (alias `crt`) — Create `n` turtles at origin with random headings and colors. The optional block initializes them.
```netlogo
crt 100 [ set color red set size 2 ]
```

`ask turtles [block]` — Each turtle runs the commands in `block` (in random order).
```netlogo
ask turtles [ fd 1 rt random 30 ]
```

`forward n` (alias `fd`) — Move forward `n` steps in the direction of current heading.

`right n` (alias `rt`) — Rotate clockwise by `n` degrees.

`left n` (alias `lt`) — Rotate counter-clockwise by `n` degrees.

`set heading n` — Set turtle heading to `n` degrees (0 = north, 90 = east, 180 = south, 270 = west).

`setxy x y` — Move turtle to absolute coordinates (`x`, `y`). Wraps if topology allows.
```netlogo
ask turtles [ setxy random-xcor random-ycor ]
```

`die` — Remove this turtle (and its links) from the model.

`hatch n [block]` — Create `n` new turtles identical to the current turtle. The block can modify the offspring.
```netlogo
ask turtles [ if energy > 50 [ hatch 1 [ set energy 25 ] ] ]
```

`move-to agent` — Move to the same location as the given agent (turtle or patch). Does not change heading.

`face agent` — Set heading to point toward the given agent.

`towards agent` — Reporter. Returns the heading from this turtle toward the given agent.

`distance agent` — Reporter. Returns the distance from this turtle to the given agent.

`patch-here` — Reporter. Returns the patch under this turtle.
```netlogo
ask turtles [ set pcolor red ]  ;; colors patch under each turtle
;; equivalent to: ask turtles [ ask patch-here [ set pcolor red ] ]
```

`pen-down` (alias `pd`) — Start drawing a trail as the turtle moves.

`pen-up` (alias `pu`) — Stop drawing a trail.

`pen-erase` (alias `pe`) — Erase trails as the turtle moves over them.

`hide-turtle` (alias `ht`) — Make this turtle invisible.

`show-turtle` (alias `st`) — Make this turtle visible.

---

## 2. Turtle Reporters

`xcor` — Current x-coordinate (float).

`ycor` — Current y-coordinate (float).

`heading` — Current heading in degrees (0-359.99...).

`color` — Current color value (number or RGB list).

`size` — Visual size of the turtle (default 1).

`who` — Unique integer ID of this turtle.

`breed` — The breed agentset this turtle belongs to.

`shape` — Current shape name (string, e.g. `"circle"`, `"default"`).

`label` — Text displayed next to the turtle. Set to `""` to hide.

`other agentset` — Returns all agents in `agentset` except the caller.
```netlogo
let nearby other turtles in-radius 3
```

`self` — Reporter. Returns the agent running the current code.

`myself` — Reporter. Inside a nested `ask` or `of`, returns the agent that initiated the outer context.
```netlogo
ask turtles [
  ask other turtles in-radius 2 [
    face myself  ;; face the turtle who asked
  ]
]
```

---

## 3. Patch Commands & Reporters

`ask patches [block]` — Each patch runs the commands in `block`.
```netlogo
ask patches [ set pcolor green ]
```

`pcolor` — The color of this patch.

`plabel` — Text label displayed on this patch.

`pxcor` — Integer x-coordinate of this patch.

`pycor` — Integer y-coordinate of this patch.

`neighbors` — Reporter. Returns the agentset of 8 surrounding patches (Moore neighborhood).

`neighbors4` — Reporter. Returns the agentset of 4 surrounding patches (Von Neumann neighborhood).

`patch-at dx dy` — Reporter. Returns the patch at relative offset (`dx`, `dy`) from this agent.
```netlogo
ask turtles [ if [pcolor] of patch-at 0 1 = red [ stop ] ]
```

`patch x y` — Reporter. Returns the patch at absolute coordinates. Coordinates are rounded to integers.
```netlogo
ask patch 0 0 [ set pcolor yellow ]
```

`sprout n [block]` — Patch command. Creates `n` turtles on this patch.
```netlogo
ask patches with [ pcolor = green ] [ sprout 1 [ set color white ] ]
```

`turtles-here` — Reporter. Returns the agentset of all turtles on this patch.

`turtles-on agent-or-agentset` — Reporter. Returns all turtles standing on the given patch(es) or the patch(es) under the given turtle(s).

---

## 4. Link Commands & Reporters

`create-link-with agent [block]` — Create an undirected link between this turtle and `agent`.
```netlogo
ask turtle 0 [ create-link-with turtle 1 [ set color red ] ]
```

`create-link-to agent [block]` — Create a directed link from this turtle to `agent`.

`create-link-from agent [block]` — Create a directed link from `agent` to this turtle.

`create-links-with agentset [block]` — Create undirected links with all turtles in the agentset.

`create-links-to agentset [block]` — Create directed links to all turtles in the agentset.

`create-links-from agentset [block]` — Create directed links from all turtles in the agentset to this turtle.

`tie` — Link command. Ties the linked turtles so that when one moves or turns, the other follows.

`untie` — Link command. Removes the tie.

`end1` — Reporter. Returns the first turtle in the link.

`end2` — Reporter. Returns the second turtle in the link.

`link-neighbors` — Turtle reporter. Returns the agentset of turtles connected by undirected links.

`in-link-neighbors` — Turtle reporter. Returns turtles connected by directed links pointing to this turtle.

`out-link-neighbors` — Turtle reporter. Returns turtles this turtle has directed links pointing to.

`my-links` — Turtle reporter. Returns all undirected links connected to this turtle.

`my-in-links` — Turtle reporter. Returns all directed links coming into this turtle.

`my-out-links` — Turtle reporter. Returns all directed links going out from this turtle.

`link-length` — Link reporter. Returns the distance between the two endpoints.

---

## 5. Agentset Operations

`count agentset` — Returns the number of agents in the agentset.
```netlogo
show count turtles with [ color = red ]
```

`any? agentset` — Returns `true` if the agentset is non-empty.
```netlogo
if any? turtles-here [ ... ]
```

`one-of agentset` — Returns a random agent from the agentset (or a random item from a list).

`n-of n agentset` — Returns an agentset of `n` randomly chosen agents (no repeats).

`max-one-of agentset [reporter]` — Returns the single agent with the maximum value of `reporter`.
```netlogo
let biggest max-one-of turtles [ size ]
```

`min-one-of agentset [reporter]` — Returns the single agent with the minimum value of `reporter`.

`max-n-of n agentset [reporter]` — Returns the `n` agents with the highest values of `reporter`.

`min-n-of n agentset [reporter]` — Returns the `n` agents with the lowest values of `reporter`.

`with [condition]` — Filters an agentset to only those satisfying `condition`.
```netlogo
ask turtles with [ color = red and size > 1 ] [ fd 2 ]
```

`sort-on [reporter] agentset` — Returns a list of agents sorted by `reporter` (ascending).

`member? agent agentset` — Returns `true` if the agent is a member of the agentset.

`member? value list` — Returns `true` if value is in the list.

`turtle-set agents...` — Creates a new agentset combining turtles from multiple sources.
```netlogo
let group turtle-set turtle 0 turtle 3 turtle 7
```

`patch-set agents...` — Creates a new agentset combining patches from multiple sources.

`link-set agents...` — Creates a new agentset combining links from multiple sources.

`[reporter] of agentset` — Returns a list of values by running `reporter` on each agent.
```netlogo
let all-ages [age] of turtles
```

`in-radius n` — Returns agents within distance `n` of the caller.
```netlogo
ask turtles [ let nearby turtles in-radius 5 ]
```

`in-cone dist angle` — Returns agents in a cone defined by distance and angle (centered on heading).

---

## 6. Math

`random n` — Returns a random integer from 0 to `n - 1` (n must be positive integer).

`random-float n` — Returns a random float from 0 to (but not including) `n`.

`abs n` — Absolute value.

`max list` — Returns the maximum value from a list of numbers.
```netlogo
show max [energy] of turtles
```

`min list` — Returns the minimum value from a list of numbers.

`mean list` — Returns the arithmetic mean of a list of numbers.

`median list` — Returns the median of a list of numbers.

`sum list` — Returns the sum of a list of numbers.
```netlogo
show sum [energy] of turtles
```

`sqrt n` — Square root.

`sin n` — Sine (argument in degrees).

`cos n` — Cosine (argument in degrees).

`atan y x` — Arctangent in degrees (note: y comes first).

`remainder a b` — Remainder of `a / b` (sign matches `a`).

`mod a b` — Modulus (result always non-negative).

`ceiling n` — Smallest integer >= `n`.

`floor n` — Largest integer <= `n`.

`round n` — Round to nearest integer (0.5 rounds to nearest even).

`ln n` — Natural logarithm.

`log n base` — Logarithm with specified base.

`exp n` — e raised to the power `n`.

`e` — Euler's number (~2.71828).

`pi` — Pi (~3.14159).

`^` — Exponentiation operator: `2 ^ 3` gives 8.

`precision n places` — Rounds `n` to the given number of decimal places.
```netlogo
show precision 3.14159 2  ;; => 3.14
```

`int n` — Truncates toward zero (removes decimal part).

`standard-deviation list` — Standard deviation of a list.

`variance list` — Variance of a list.

---

## 7. List Operations

`list val1 val2 ...` — Creates a list from the given values.
```netlogo
let my-list list 1 2          ;; => [1 2]
let big (list 1 2 3 4 5)      ;; parentheses needed for 3+ args
```

`item index list` — Returns the element at position `index` (0-based).

`length list` — Returns the number of items in the list.

`first list` — Returns the first item.

`last list` — Returns the last item.

`but-first list` (alias `bf`) — Returns all items except the first.

`but-last list` (alias `bl`) — Returns all items except the last.

`fput value list` — Adds `value` to the front of the list.

`lput value list` — Adds `value` to the end of the list.

`remove value list` — Returns the list with all occurrences of `value` removed.

`remove-item index list` — Returns the list with the item at `index` removed.

`replace-item index list value` — Returns the list with `index` position replaced by `value`.

`sort list` — Returns a new list sorted in ascending order.

`sort-by [comparator] list` — Returns a sorted list using a custom comparator.
```netlogo
sort-by [ [a b] -> a > b ] [3 1 2]  ;; => [3 2 1]
```

`map [reporter] list` — Applies the reporter to each element; returns a new list.
```netlogo
show map [ x -> x * 2 ] [1 2 3]  ;; => [2 4 6]
```

`filter [reporter] list` — Returns a list of items for which the reporter is `true`.
```netlogo
show filter [ x -> x > 2 ] [1 2 3 4]  ;; => [3 4]
```

`reduce [reporter] list` — Combines all items using a binary reporter, left to right.
```netlogo
show reduce [ [a b] -> a + b ] [1 2 3 4]  ;; => 10
```

`foreach list [block]` — Runs the block once for each element.
```netlogo
foreach [1 2 3] [ x -> show x ]
```

`range args` — Generates a list of numbers.
```netlogo
show range 5          ;; => [0 1 2 3 4]
show range 2 5        ;; => [2 3 4]
show range 0 10 3     ;; => [0 3 6 9]
```

`n-values n [reporter]` — Generates a list of `n` values by running reporter with each index.
```netlogo
show n-values 5 [ i -> i * i ]  ;; => [0 1 4 9 16]
```

`sentence val1 val2` (alias `se`) — Concatenates lists and/or values into a single flat list.
```netlogo
show sentence [1 2] [3 4]  ;; => [1 2 3 4]
```

`sublist list start end` — Returns items from index `start` up to (but not including) `end`.

`position value list` — Returns the index of the first occurrence of `value`, or `false` if not found.

`empty? list` — Returns `true` if the list is empty.

`is-list? value` — Returns `true` if value is a list.

---

## 8. String Operations

`word val1 val2 ...` — Concatenates values into a single string.
```netlogo
show word "hello" "-" "world"    ;; => "hello-world"
show (word "x=" 5 " y=" 10)     ;; parentheses for 3+ args => "x=5 y=10"
```

`substring string start end` — Returns characters from index `start` up to (but not including) `end`.
```netlogo
show substring "hello" 1 3  ;; => "el"
```

`position string1 string2` — Returns the index of the first occurrence of `string1` within `string2`, or `false`.

`length string` — Returns the number of characters in the string.

`is-string? value` — Returns `true` if value is a string.

`read-from-string string` — Parses a string as a NetLogo literal value.
```netlogo
show read-from-string "42"       ;; => 42
show read-from-string "[1 2 3]"  ;; => [1 2 3]
```

---

## 9. Control Flow

`if condition [block]` — Run `block` if `condition` is `true`.
```netlogo
if count turtles > 100 [ show "many turtles" ]
```

`ifelse condition [block1] [block2]` — Run `block1` if true, `block2` if false.
```netlogo
ifelse any? turtles-here
  [ set color red ]
  [ set color blue ]
```

`ifelse-value condition [expr1] [expr2]` — Inline conditional reporter (ternary).
```netlogo
set color ifelse-value (energy > 50) [ green ] [ red ]
```

`while [condition] [block]` — Repeat `block` as long as `condition` is `true`.
```netlogo
while [count turtles < 100] [ crt 1 ]
```

`repeat n [block]` — Run `block` exactly `n` times.
```netlogo
repeat 4 [ fd 1 rt 90 ]  ;; draw a square
```

`loop [block]` — Run `block` forever (use `stop` to exit).

`stop` — Exit the current procedure (or stop the current agent in `ask`).

`every n [block]` — Run `block` at most once every `n` seconds of wall-clock time. Used in forever buttons.
```netlogo
every 0.5 [ tick ]
```

`wait n` — Pause execution for `n` seconds.

`carefully [block1] [block2]` — Run `block1`; if a runtime error occurs, run `block2` instead.
```netlogo
carefully [ set x 1 / y ] [ set x 0 ]
```

`error-message` — Reporter. Inside the second block of `carefully`, returns the error message string.

`error string` — Immediately raises a runtime error with the given message.

`run string-or-command` — Runs a string as NetLogo code, or runs an anonymous command.

`runresult string-or-reporter` — Runs a string as a reporter and returns the result.

`->` — Arrow syntax for anonymous procedures.
```netlogo
let double [ x -> x * 2 ]
show (runresult double 5)  ;; => 10
```

---

## 10. Breeds

**Breed declarations** go at the top of the Code tab, before any procedures.

```netlogo
breed [wolves wolf]           ;; plural then singular
breed [sheep a-sheep]

directed-link-breed [streets street]
undirected-link-breed [friendships friendship]
```

After declaring breeds, you get automatically generated commands and reporters:

- `create-wolves n [block]` — breed-specific turtle creation.
- `wolves` — agentset of all wolves.
- `is-wolf? agent` — breed check reporter.
- `wolves-own [var1 var2]` — breed-specific variables.
- `wolves-here` — wolves on this patch.
- `wolves-at dx dy` — wolves at relative offset.
- `wolves-on agent-or-agentset` — wolves on given patches/turtles.

For link breeds:
- `create-street-to`, `create-street-from` (directed)
- `create-friendship-with` (undirected)
- `streets-own [var]` — link-breed-specific variables.
- `is-street? link` — breed check.

`set breed wolves` — Change a turtle's breed at runtime.

---

## 11. Variables

**Global variables:**
```netlogo
globals [ population-limit max-energy ]
```

**Agent variables:**
```netlogo
turtles-own [ energy speed age ]
patches-own [ fertility ]
links-own [ strength ]
```

`let name value` — Declare a new local variable.
```netlogo
let total count turtles
```

`set variable value` — Assign a new value to an existing variable (global, agent, or local).
```netlogo
set color blue
set energy energy - 1
```

Variables can be read from another agent with `of`:
```netlogo
show [energy] of turtle 0
```

---

## 12. World & Ticks

`clear-all` (alias `ca`) — Reset everything: turtles, patches, drawing, plots, output, ticks.

`clear-turtles` (alias `ct`) — Remove all turtles and links.

`clear-patches` (alias `cp`) — Reset all patch variables to defaults.

`clear-drawing` (alias `cd`) — Clear all pen drawings.

`clear-output` — Clear the output area.

`clear-plot` / `clear-all-plots` — Clear current/all plots.

`reset-ticks` — Set the tick counter to 0. Usually called at the end of `setup`.

`tick` — Advance the tick counter by 1. Updates all plots.

`tick-advance n` — Advance the tick counter by `n` (can be fractional).

`ticks` — Reporter. Returns the current tick count.

`resize-world min-px max-px min-py max-py` — Change world dimensions.
```netlogo
resize-world -25 25 -25 25  ;; 51x51 world
```

`set-patch-size n` — Set the pixel size of each patch in the view.

`max-pxcor` — Reporter. Maximum patch x-coordinate.

`min-pxcor` — Reporter. Minimum patch x-coordinate.

`max-pycor` — Reporter. Maximum patch y-coordinate.

`min-pycor` — Reporter. Minimum patch y-coordinate.

`world-width` — Reporter. Width of world in patches.

`world-height` — Reporter. Height of world in patches.

`wrap` — World topology controls are set via the Interface (wrapping on/off per axis). In code, use `__change-topology wrap-x? wrap-y?` (rarely needed).

---

## 13. I/O (Input / Output)

`show value` — Prints the value to the command center, prefixed with the calling agent.
```netlogo
show count turtles  ;; observer: 42
```

`print value` — Prints the value to the command center (no agent prefix).

`type value` — Like `print` but without a newline at the end.

`write value` — Like `print` but strings are quoted and readable by `read-from-string`.

`output-print value` / `output-show value` / `output-type value` / `output-write value` — Print to the output widget instead of the command center.

`user-message string` — Show a popup dialog with a message.

`user-input string` — Show a popup dialog and return the user's typed response as a string.

`user-yes-or-no? string` — Show a dialog with Yes/No buttons; returns `true` or `false`.

**File I/O:**

`file-open path` — Open a file for reading or writing.
```netlogo
file-open "data.csv"
```

`file-read` — Read the next value from the file.

`file-read-line` — Read the next line as a string.

`file-read-characters n` — Read `n` characters.

`file-write value` — Write a value to the file (readable format).

`file-print value` — Write a value followed by a newline.

`file-type value` — Write a value with no newline.

`file-close` — Close the most recently opened file.

`file-close-all` — Close all open files.

`file-exists? path` — Returns `true` if the file exists.

`file-delete path` — Delete a file.

`file-at-end?` — Returns `true` if at end of file.

**Export:**

`export-world path` — Save the entire model state to a CSV file.

`export-view path` — Save the current view as a PNG image.

`export-plot name path` — Export a plot's data to CSV.

`export-all-plots path` — Export all plots' data to CSV.

`export-output path` — Export the output area to a text file.

**Import:**

`import-world path` — Restore model state from exported CSV.

`import-pcolors path` — Set patch colors from an image file.

`import-pcolors-rgb path` — Set patch colors from an image using RGB lists.

---

## 14. Color

NetLogo uses a numeric color space from 0 to 139.9. Each base color is a multiple of 10.

**Color constants:**

| Constant | Value | Constant | Value |
|----------|-------|----------|-------|
| `black`  | 0     | `gray`   | 5     |
| `white`  | 9.9   | `red`    | 15    |
| `orange` | 25    | `brown`  | 35    |
| `yellow` | 45    | `green`  | 55    |
| `lime`   | 65    | `turquoise` | 75 |
| `cyan`   | 85    | `sky`    | 95    |
| `blue`   | 105   | `violet` | 115   |
| `magenta`| 125   | `pink`   | 135   |

Adding/subtracting from a base color adjusts shade: `red + 2` = light red, `red - 3` = dark red. Valid offsets: -5 to +4.9.

`scale-color color value min max` — Maps a numeric value to a shade of a base color. Returns lighter shades for higher values.
```netlogo
ask patches [ set pcolor scale-color green fertility 0 10 ]
```

`extract-hsb color` — Returns a 3-element list `[hue saturation brightness]` for a NetLogo color number.

`approximate-hsb hue sat bright` — Returns the NetLogo color number closest to the given HSB values.

`approximate-rgb r g b` — Returns the NetLogo color number closest to the given RGB values.

`rgb r g b` — Returns an RGB list `[r g b]` (0-255 each) that can be used directly as a color.
```netlogo
set color rgb 255 128 0  ;; orange via RGB
```

`hsb h s b` — Returns an RGB list from HSB values.

`base-colors` — Reporter. Returns a list of the 14 base color values.

`color` — A turtle/link variable. Can be set to a number (0-139.9) or an RGB/RGBA list.
```netlogo
set color [255 0 0]       ;; red via RGB list
set color [255 0 0 128]   ;; semi-transparent red (RGBA)
```

`wrap-color n` — Wraps a number into the valid NetLogo color range (0 to 140).

---

## 15. Random

`random-seed n` — Set the random seed for reproducibility. Use in `setup` before any random operations.
```netlogo
random-seed 42
```

`random n` — Returns a random integer from 0 to `n - 1`.

`random-float n` — Returns a random float from 0 (inclusive) to `n` (exclusive).

`random-xcor` — Returns a random float in the range of valid turtle x-coordinates.

`random-ycor` — Returns a random float in the range of valid turtle y-coordinates.

`random-pxcor` — Returns a random integer in the range of valid patch x-coordinates.

`random-pycor` — Returns a random integer in the range of valid patch y-coordinates.

`random-normal mean stddev` — Returns a random number from a normal distribution.
```netlogo
set energy random-normal 50 10  ;; mean=50, stddev=10
```

`random-poisson mean` — Returns a random integer from a Poisson distribution.

`random-exponential mean` — Returns a random float from an exponential distribution.

`random-gamma alpha lambda` — Returns a random float from a gamma distribution.

`one-of list-or-agentset` — Returns a uniformly random element.

`n-of n list-or-agentset` — Returns `n` random elements without replacement.

`up-to-n-of n agentset` — Like `n-of` but does not error if the agentset has fewer than `n` agents.

---

## Common Patterns

**Typical `setup` procedure:**
```netlogo
to setup
  clear-all
  create-turtles 100 [
    setxy random-xcor random-ycor
    set color one-of base-colors
    set size 1.5
  ]
  ask patches [
    set pcolor green
  ]
  reset-ticks
end
```

**Typical `go` procedure:**
```netlogo
to go
  ask turtles [
    rt random 30 - 15
    fd 1
    if pcolor = red [ set energy energy - 1 ]
    if energy <= 0 [ die ]
  ]
  tick
end
```

**Using `of` to collect values:**
```netlogo
let energies [energy] of turtles
show mean energies
show max energies
```

**Filtering with `with`:**
```netlogo
let hungry turtles with [ energy < 10 ]
ask hungry [ set color red ]
```

**Anonymous procedures (lambdas):**
```netlogo
let squares map [ x -> x ^ 2 ] range 10
let evens filter [ x -> x mod 2 = 0 ] range 20
```
