"""Generates the market_sim NetLogo model source.

The model implements ONLY the social physics — exposure delivery, word-of-
mouth scheduling, sentiment drift, funnel coloring. All cognition lives in
Python; the orchestrator interleaves ``go`` with batched reads/writes.

Rule semantics must stay in lockstep with ``worlds.PythonWorld`` (the
reference implementation) — see the contract comment in ``worlds.py``.
"""

from __future__ import annotations

from typing import Any

MODEL_CODE = """\
globals [
  channel-type          ;; "email" | "paid_social" | "organic"
  send-tick
  reach                 ;; fraction of the audience deliverable, 0-1
  impressions-per-tick  ;; paid_social: impressions per tick as reach fraction
  frequency-cap
  wom-this-tick
  wom-total
]

turtles-own [
  state                 ;; unaware exposed engaged clicked converted ignored annoyed
  sentiment             ;; -1 .. 1
  susceptibility        ;; DeGroot drift weight, set per persona from Python
  reach-member?
  exposure-count
  exposure-pending?     ;; waiting for a cognition decision
  exp-social?
  source-who
  pending-share?        ;; decision said share -> propagate next go
  shared?
  scheduled             ;; list of [fire-tick source-who] word-of-mouth deliveries
]

to setup-world [ seed n ]
  ;; clear-all resets ALL globals — campaign params must be set AFTERWARDS
  ;; via configure-campaign, never before this call.
  clear-all
  random-seed seed
  create-turtles n [
    set state "unaware"
    set sentiment 0
    set susceptibility 0.5
    set exposure-count 0
    set exposure-pending? false
    set exp-social? false
    set source-who -1
    set pending-share? false
    set shared? false
    set scheduled []
    set reach-member? false
    set shape "circle"
    set size 0.8
    setxy random-xcor random-ycor
    recolor
  ]
  set wom-this-tick 0
  set wom-total 0
  reset-ticks
end

to configure-campaign [ channel stick sreach imp cap ]
  set channel-type channel
  set send-tick stick
  set reach sreach
  set impressions-per-tick imp
  set frequency-cap cap
  ask turtles [ set reach-member? (random-float 1 < reach) ]
end

to recolor
  set color gray - 2
  if state = "exposed"   [ set color yellow ]
  if state = "engaged"   [ set color orange ]
  if state = "clicked"   [ set color sky ]
  if state = "converted" [ set color green ]
  if state = "ignored"   [ set color gray + 2 ]
  if state = "annoyed"   [ set color red ]
end

to-report receptive?
  report (state = "unaware") or (state = "exposed") or
         (state = "ignored") or (state = "engaged")
end

to go
  set wom-this-tick 0
  tick
  deliver-direct
  fire-scheduled
  propagate-shares
  drift-sentiment
  ask turtles [ recolor ]
end

to deliver-direct
  if (channel-type = "email") or (channel-type = "organic") [
    if ticks = send-tick [
      ask turtles with [ reach-member? and receptive? ] [
        receive-exposure false -1
      ]
    ]
  ]
  if channel-type = "paid_social" [
    if ticks >= send-tick [
      let eligible turtles with [
        reach-member? and receptive? and
        (exposure-count < frequency-cap) and (not exposure-pending?)
      ]
      let n-imp round (impressions-per-tick * count turtles with [ reach-member? ])
      ask n-of (min (list n-imp (count eligible))) eligible [
        receive-exposure false -1
      ]
    ]
  ]
end

to receive-exposure [ social? src ]
  if exposure-pending? [ stop ]
  set exposure-pending? true
  set exp-social? social?
  set source-who src
  set exposure-count exposure-count + 1
  if state = "unaware" [ set state "exposed" ]
  if social? [
    set wom-this-tick wom-this-tick + 1
    set wom-total wom-total + 1
  ]
end

to fire-scheduled
  ask turtles with [ not empty? scheduled ] [
    let due filter [ s -> (first s) <= ticks ] scheduled
    set scheduled filter [ s -> (first s) > ticks ] scheduled
    if (not empty? due) and receptive? and
       (exposure-count < frequency-cap) and (not exposure-pending?) [
      receive-exposure true (item 1 (first due))
    ]
  ]
end

to propagate-shares
  ask turtles with [ pending-share? ] [
    let src who
    ask link-neighbors with [ receptive? and (exposure-count < frequency-cap) ] [
      set scheduled lput (list (ticks + 1 + random 5) src) scheduled
    ]
    set pending-share? false
    set shared? true
  ]
end

to drift-sentiment
  ask turtles [
    let opinionated link-neighbors with [ state != "unaware" ]
    if any? opinionated [
      let target mean [ sentiment ] of opinionated
      set sentiment sentiment + (susceptibility * 0.1) * (target - sentiment)
    ]
  ]
end

to-report pending-exposures
  ;; numbers only — pynetlogo cannot marshal booleans inside nested lists,
  ;; so exp-social? is encoded as 1/0.
  report map [ t ->
    (list ([who] of t) (ifelse-value ([exp-social?] of t) [1] [0])
          ([source-who] of t) ([exposure-count] of t) ([sentiment] of t))
  ] sort turtles with [ exposure-pending? ]
end

to-report state-counts
  report (list
    (count turtles with [ state = "unaware" ])
    (count turtles with [ state = "exposed" ])
    (count turtles with [ state = "engaged" ])
    (count turtles with [ state = "clicked" ])
    (count turtles with [ state = "converted" ])
    (count turtles with [ state = "ignored" ])
    (count turtles with [ state = "annoyed" ]))
end

to-report quiet?
  let anything-active any? turtles with [
    exposure-pending? or pending-share? or (not empty? scheduled)
  ]
  let direct-possible? false
  if (channel-type = "email") or (channel-type = "organic") [
    set direct-possible? (ticks < send-tick)
  ]
  if channel-type = "paid_social" [
    set direct-possible? any? turtles with [
      reach-member? and receptive? and (exposure-count < frequency-cap)
    ]
  ]
  report (not anything-active) and (not direct-possible?)
end
"""


def market_model_code() -> str:
    """The NetLogo procedures for the market simulation model."""
    return MODEL_CODE


def market_model_widgets() -> list[dict[str, Any]]:
    """Interface widgets for the generated model (monitors + funnel plot).

    Matches the widget schema of ``netlogo_mcp.tools.create_model``. No
    setup/go buttons — the orchestrator drives the model; monitors and the
    plot make the GUI demo readable.
    """
    return [
        {"type": "monitor", "code": "ticks", "label": "hour", "precision": 0},
        {
            "type": "monitor",
            "code": "count turtles with [ state = \"converted\" ]",
            "label": "converted",
            "precision": 0,
        },
        {
            "type": "monitor",
            "code": "count turtles with [ state = \"clicked\" ]",
            "label": "clicked",
            "precision": 0,
        },
        {
            "type": "monitor",
            "code": "wom-total",
            "label": "word-of-mouth",
            "precision": 0,
        },
        {
            "type": "plot",
            "label": "funnel",
            "x_axis": "hour",
            "y_axis": "people",
            "pens": [
                {
                    "code": "plot count turtles with [ state = \"exposed\" ]",
                    "label": "exposed",
                    "color": "yellow",
                },
                {
                    "code": "plot count turtles with [ state = \"engaged\" ]",
                    "label": "engaged",
                    "color": "orange",
                },
                {
                    "code": "plot count turtles with [ state = \"clicked\" ]",
                    "label": "clicked",
                    "color": "sky",
                },
                {
                    "code": "plot count turtles with [ state = \"converted\" ]",
                    "label": "converted",
                    "color": "green",
                },
                {
                    "code": "plot count turtles with [ state = \"ignored\" ]",
                    "label": "ignored",
                    "color": "gray",
                },
            ],
        },
    ]
