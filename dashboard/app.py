"""SynthAudience dashboard — browse campaign runs, funnels, and verbatims.

Run with:
    uv run --extra dashboard streamlit run dashboard/app.py

Reads the SQLite event stores under ``market_data/runs`` (or ``$SYNTH_DATA_DIR``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from netlogo_mcp.market.analytics import (  # noqa: E402
    compare_variants,
    funnel_summary,
    mine_objections,
    segment_breakdown,
    wom_stats,
)
from netlogo_mcp.market.config import get_runs_dir  # noqa: E402
from netlogo_mcp.market.personas import load_audience  # noqa: E402
from netlogo_mcp.market.store import EventStore  # noqa: E402

st.set_page_config(page_title="SynthAudience", page_icon="🧪", layout="wide")
st.title("🧪 SynthAudience — campaign pre-flight results")

dbs = sorted(get_runs_dir().glob("*.sqlite"))
if not dbs:
    st.info(
        "No campaign runs found. Run a campaign first (MCP `run_campaign` "
        "or `validation/spike/spike.py`)."
    )
    st.stop()

campaign_file = st.sidebar.selectbox(
    "Campaign", dbs, format_func=lambda p: p.stem
)
store = EventStore(campaign_file.stem, path=str(campaign_file))
runs = store.runs_df()
if runs.empty:
    st.warning("This campaign has no runs yet.")
    st.stop()

audience_name = runs.iloc[0]["audience"]
try:
    audience = load_audience(audience_name)
except FileNotFoundError:
    st.error(f"Audience '{audience_name}' not found in market_data/audiences.")
    st.stop()

st.sidebar.metric("audience", f"{audience_name} ({audience.size})")
st.sidebar.metric("runs", len(runs))
st.sidebar.metric("cognition calls", int(runs["llm_calls"].sum()))
engines = ", ".join(sorted(set(runs["engine"])))
st.sidebar.caption(f"engine(s): {engines}")
if "Heuristic" in engines:
    st.sidebar.warning(
        "Heuristic cognition (no LLM). Set SYNTH_LLM_MODE=live for "
        "persona-driven reactions."
    )

# ── Funnel ───────────────────────────────────────────────────────────────────

st.header("Funnel by variant")
funnel = funnel_summary(store, audience)
cols = st.columns(max(1, len(funnel)))
for col, (vid, v) in zip(cols, funnel.items(), strict=False):
    with col:
        st.subheader(f"variant {vid}")
        m = v["metrics"]
        st.metric("attention gate", f"{m['gate']['mean']:.1%}")
        st.metric("click-through", f"{m['click']['mean']:.1%}")
        st.metric("conversion", f"{m['convert']['mean']:.1%}")
        st.metric(
            "audience conversion",
            f"{m['conversion_of_audience']['mean']:.2%}",
        )

rows = []
for vid, v in funnel.items():
    for stage in ("reach", "gate", "click", "convert", "annoyance"):
        s = v["metrics"][stage]
        rows.append(
            {"variant": vid, "stage": stage, "rate": 100 * s["mean"],
             "lo": 100 * s["lo"], "hi": 100 * s["hi"]}
        )
funnel_df = pd.DataFrame(rows)
st.bar_chart(funnel_df, x="stage", y="rate", color="variant", height=320)

# ── A/B ──────────────────────────────────────────────────────────────────────

comparisons = compare_variants(store, audience)
if comparisons:
    st.header("A/B verdict")
    st.dataframe(pd.DataFrame(comparisons), use_container_width=True)

# ── Per-variant detail ───────────────────────────────────────────────────────

variant = st.selectbox("Variant detail", sorted(funnel))

left, right = st.columns(2)
with left:
    st.subheader("Segments")
    seg = pd.DataFrame(segment_breakdown(store, audience, variant))
    if not seg.empty:
        dim = st.radio(
            "dimension", sorted(seg["dimension"].unique()), horizontal=True
        )
        view = seg[seg["dimension"] == dim].drop(columns=["dimension"])
        st.dataframe(
            view.style.format(
                {
                    "engaged_rate": "{:.0%}",
                    "click_rate": "{:.0%}",
                    "conversion_rate": "{:.1%}",
                    "annoyed_rate": "{:.0%}",
                    "mean_sentiment": "{:+.2f}",
                }
            ),
            use_container_width=True,
        )

with right:
    st.subheader("Objection themes")
    for theme in mine_objections(store, variant):
        with st.expander(f"{theme['theme']}  ({theme['count']} mentions)"):
            for q in theme["quotes"]:
                st.markdown(f"> {q}")

    st.subheader("Word of mouth")
    st.json(wom_stats(store, variant))

# ── Timeline + verbatims ─────────────────────────────────────────────────────

st.header("Funnel over time")
tm = store.tick_metrics_df()
run_ids = store.completed_run_ids().get(variant, [])
if run_ids and not tm.empty:
    first = tm[tm["run_id"] == run_ids[0]].set_index("tick")
    st.line_chart(
        first[["exposed", "engaged", "clicked", "converted", "ignored"]],
        height=300,
    )

st.header("Decision log")
decisions = store.decisions_df(run_ids)
if not decisions.empty:
    state_filter = st.multiselect(
        "states", sorted(decisions["state"].unique()),
        default=sorted(decisions["state"].unique()),
    )
    view = decisions[decisions["state"].isin(state_filter)][
        ["tick", "persona_id", "exposure_type", "stage1_action", "action",
         "state", "sentiment", "reason", "objections"]
    ]
    st.dataframe(view, use_container_width=True, height=380)
    st.download_button(
        "download decisions CSV",
        view.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_file.stem}_{variant}_decisions.csv",
    )

st.caption(
    "Relative comparisons (variant/segment ranking, objections) are the "
    "trustworthy output. Absolute rates need calibration against real "
    "campaign data. A synthetic audience is a rehearsal, not the market."
)
