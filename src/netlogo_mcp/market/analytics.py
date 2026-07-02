"""Analytics — turn the event store into decision-grade numbers.

- Funnel rates per variant with confidence intervals across replicates.
- Segment breakdown (who converts, who gets annoyed).
- Objection mining: TF-IDF + k-means clustering of verbatim reasons.
- Paired variant comparison with significance tests.
- Word-of-mouth amplification stats.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from .calibration import Calibration, load_base_rates
from .schemas import Audience
from .store import EventStore

# ── Helpers ──────────────────────────────────────────────────────────────────

FINAL_STATES = ("engaged", "clicked", "converted", "ignored", "annoyed")


def _final_counts_per_run(store: EventStore, run_id: str) -> dict[str, int] | None:
    tm = store.tick_metrics_df([run_id])
    if tm.empty:
        return None
    last = tm.sort_values("tick").iloc[-1]
    return {
        s: int(last[s])
        for s in ("unaware", "exposed", "engaged", "clicked", "converted",
                  "ignored", "annoyed")
    }


def _rates_from_counts(counts: dict[str, int], size: int) -> dict[str, float]:
    reached = size - counts["unaware"]
    engaged_total = counts["engaged"] + counts["clicked"] + counts["converted"]
    clicked_total = counts["clicked"] + counts["converted"]
    return {
        "reach": reached / max(1, size),
        "gate": engaged_total / max(1, reached),
        "click": clicked_total / max(1, engaged_total),
        "convert": counts["converted"] / max(1, clicked_total),
        "conversion_of_audience": counts["converted"] / max(1, size),
        "annoyance": counts["annoyed"] / max(1, reached),
    }


def _mean_ci(values: list[float], confidence: float = 0.95) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    if len(arr) < 2:
        return {"mean": mean, "lo": mean, "hi": mean}
    from scipy import stats

    sem = stats.sem(arr)
    if sem == 0:
        return {"mean": mean, "lo": mean, "hi": mean}
    lo, hi = stats.t.interval(confidence, len(arr) - 1, loc=mean, scale=sem)
    return {"mean": mean, "lo": float(max(0, lo)), "hi": float(min(1, hi))}


# ── Funnel ───────────────────────────────────────────────────────────────────


def funnel_summary(
    store: EventStore,
    audience: Audience,
    calibration: Calibration | None = None,
    channel_by_variant: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Per-variant funnel rates with CIs, plus calibrated + benchmark views."""
    calibration = calibration or Calibration.load()
    out: dict[str, Any] = {}
    for stimulus_id, run_ids in store.completed_run_ids().items():
        per_run_rates: list[dict[str, float]] = []
        per_run_counts: list[dict[str, int]] = []
        for rid in run_ids:
            counts = _final_counts_per_run(store, rid)
            if counts is None:
                continue
            per_run_counts.append(counts)
            per_run_rates.append(_rates_from_counts(counts, audience.size))
        if not per_run_rates:
            continue

        channel = (channel_by_variant or {}).get(stimulus_id, "email")
        metrics = {
            metric: _mean_ci([r[metric] for r in per_run_rates])
            for metric in per_run_rates[0]
        }
        raw_stage_rates = {
            stage: metrics[stage]["mean"] for stage in ("gate", "click", "convert")
        }
        out[stimulus_id] = {
            "replicates": len(per_run_rates),
            "metrics": metrics,
            "raw": raw_stage_rates,
            "calibrated": calibration.apply_funnel(channel, raw_stage_rates),
            "calibration_applied": not calibration.is_identity(),
            "mean_final_counts": {
                k: float(np.mean([c[k] for c in per_run_counts]))
                for k in per_run_counts[0]
            },
        }
    return out


# ── Segments ─────────────────────────────────────────────────────────────────

_AGE_BINS = [(0, 24, "≤24"), (25, 34, "25-34"), (35, 44, "35-44"),
             (45, 54, "45-54"), (55, 200, "55+")]


def _age_bracket(age: int) -> str:
    for lo, hi, label in _AGE_BINS:
        if lo <= age <= hi:
            return label
    return "?"


def _final_outcomes(store: EventStore, run_ids: list[str]) -> pd.DataFrame:
    """One row per (run, agent): the agent's LAST decision in that run."""
    dec = store.decisions_df(run_ids)
    if dec.empty:
        return dec
    dec = dec.sort_values(["run_id", "agent_index", "tick", "id"])
    return dec.groupby(["run_id", "agent_index"], as_index=False).last()


def segment_breakdown(
    store: EventStore, audience: Audience, stimulus_id: str
) -> list[dict[str, Any]]:
    """Outcome rates per persona segment for one variant."""
    run_ids = store.completed_run_ids().get(stimulus_id, [])
    outcomes = _final_outcomes(store, run_ids)
    if outcomes.empty:
        return []

    personas = audience.personas
    rows = []
    for _, r in outcomes.iterrows():
        p = personas[int(r["agent_index"])]
        rows.append(
            {
                "age_bracket": _age_bracket(p.age),
                "income": p.income_bracket,
                "objection_style": p.objection_style,
                "archetype": p.archetype,
                "state": r["state"],
                "sentiment": float(r["sentiment"]),
            }
        )
    df = pd.DataFrame(rows)

    segments: list[dict[str, Any]] = []
    for dim in ("objection_style", "income", "age_bracket", "archetype"):
        for value, group in df.groupby(dim):
            n = len(group)
            segments.append(
                {
                    "dimension": dim,
                    "segment": str(value),
                    "n": n,
                    "engaged_rate": float(
                        group["state"].isin(["engaged", "clicked", "converted"]).mean()
                    ),
                    "click_rate": float(
                        group["state"].isin(["clicked", "converted"]).mean()
                    ),
                    "conversion_rate": float((group["state"] == "converted").mean()),
                    "annoyed_rate": float((group["state"] == "annoyed").mean()),
                    "mean_sentiment": float(group["sentiment"].mean()),
                }
            )
    return segments


# ── Objection mining ─────────────────────────────────────────────────────────


def _collect_verbatims(store: EventStore, run_ids: list[str]) -> list[str]:
    dec = store.decisions_df(run_ids)
    if dec.empty:
        return []
    texts: list[str] = []
    for _, r in dec.iterrows():
        if r["reason"]:
            texts.append(str(r["reason"]))
        try:
            texts.extend(str(o) for o in json.loads(r["objections"] or "[]") if o)
        except (json.JSONDecodeError, TypeError):
            pass
    # Dedup near-identical strings but keep multiplicity information.
    return [t.strip() for t in texts if len(t.strip()) >= 8]


def mine_objections(
    store: EventStore, stimulus_id: str, n_themes: int = 5
) -> list[dict[str, Any]]:
    """Cluster verbatim reasons/objections into themes.

    TF-IDF + k-means — works offline. With a live LLM you can additionally
    summarize each theme, but the clusters themselves need no model.
    """
    run_ids = store.completed_run_ids().get(stimulus_id, [])
    texts = _collect_verbatims(store, run_ids)
    if len(texts) < 4:
        return [
            {"theme": t, "count": 1, "quotes": [t]} for t in texts
        ]

    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    vec = TfidfVectorizer(stop_words="english", max_features=500, min_df=1)
    X = vec.fit_transform(texts)
    k = int(min(n_themes, max(2, len(set(texts)) // 4)))
    km = KMeans(n_clusters=k, n_init=10, random_state=0)
    labels = km.fit_predict(X)

    terms = np.array(vec.get_feature_names_out())
    themes: list[dict[str, Any]] = []
    for c in range(k):
        members = [texts[i] for i in range(len(texts)) if labels[i] == c]
        if not members:
            continue
        centroid = km.cluster_centers_[c]
        top_terms = terms[np.argsort(-centroid)[:4]]
        # Frequency-ranked representative quotes.
        counts: dict[str, int] = {}
        for m in members:
            counts[m] = counts.get(m, 0) + 1
        quotes = sorted(counts, key=lambda q: -counts[q])[:3]
        themes.append(
            {
                "theme": ", ".join(t for t in top_terms if not t.isdigit()),
                "count": len(members),
                "quotes": quotes,
            }
        )
    themes.sort(key=lambda t: -t["count"])
    return themes


# ── Variant comparison ───────────────────────────────────────────────────────


def compare_variants(
    store: EventStore, audience: Audience
) -> list[dict[str, Any]]:
    """Pairwise comparison of variants on audience-level conversion and
    engagement, using the paired-replicate design + two-proportion z-test."""
    from scipy import stats

    by_variant: dict[str, list[dict[str, int]]] = {}
    for stimulus_id, run_ids in store.completed_run_ids().items():
        counts = [_final_counts_per_run(store, r) for r in run_ids]
        by_variant[stimulus_id] = [c for c in counts if c]

    variants = sorted(by_variant)
    comparisons: list[dict[str, Any]] = []
    for i in range(len(variants)):
        for j in range(i + 1, len(variants)):
            a, b = variants[i], variants[j]
            ca, cb = by_variant[a], by_variant[b]
            n_a = audience.size * len(ca)
            n_b = audience.size * len(cb)
            for metric, num in (
                ("conversion", lambda c: c["converted"]),
                ("click", lambda c: c["clicked"] + c["converted"]),
                ("engagement", lambda c: c["engaged"] + c["clicked"] + c["converted"]),
            ):
                x_a = sum(num(c) for c in ca)
                x_b = sum(num(c) for c in cb)
                p_a, p_b = x_a / max(1, n_a), x_b / max(1, n_b)
                pooled = (x_a + x_b) / max(1, n_a + n_b)
                se = np.sqrt(pooled * (1 - pooled) * (1 / max(1, n_a) + 1 / max(1, n_b)))
                z = (p_a - p_b) / se if se > 0 else 0.0
                p_value = float(2 * (1 - stats.norm.cdf(abs(z))))
                winner = a if p_a > p_b else b if p_b > p_a else "tie"
                comparisons.append(
                    {
                        "variant_a": a,
                        "variant_b": b,
                        "metric": metric,
                        "rate_a": round(p_a, 4),
                        "rate_b": round(p_b, 4),
                        "lift_pct": round(
                            100 * (max(p_a, p_b) / max(1e-9, min(p_a, p_b)) - 1), 1
                        )
                        if min(p_a, p_b) > 0
                        else None,
                        "winner": winner,
                        "p_value": round(p_value, 4),
                        "significant": p_value < 0.05,
                    }
                )
    return comparisons


# ── Word of mouth ────────────────────────────────────────────────────────────


def wom_stats(store: EventStore, stimulus_id: str) -> dict[str, Any]:
    run_ids = store.completed_run_ids().get(stimulus_id, [])
    dec = store.decisions_df(run_ids)
    if dec.empty:
        return {"social_exposures": 0, "direct_exposures": 0, "amplification": 0.0}
    social = int((dec["exposure_type"] == "social").sum())
    direct = int((dec["exposure_type"] == "direct").sum())
    sharers = int(dec["will_share"].sum())
    return {
        "social_exposures": social,
        "direct_exposures": direct,
        "sharers": sharers,
        "amplification": round(social / max(1, direct), 3),
        "social_conversion_rate": round(
            float(
                (dec[dec["exposure_type"] == "social"]["state"] == "converted").mean()
            )
            if social
            else 0.0,
            4,
        ),
        "direct_conversion_rate": round(
            float(
                (dec[dec["exposure_type"] == "direct"]["state"] == "converted").mean()
            )
            if direct
            else 0.0,
            4,
        ),
    }


# ── Weak points ──────────────────────────────────────────────────────────────


def weak_points(
    store: EventStore,
    audience: Audience,
    stimulus_id: str,
    channel: str = "email",
) -> list[str]:
    """Plain-language diagnosis of where the funnel leaks most."""
    findings: list[str] = []
    summary = funnel_summary(store, audience).get(stimulus_id)
    if not summary:
        return findings
    base = load_base_rates().get(channel, {})
    labels = {
        "gate": "attention gate (teaser/subject line)",
        "click": "click-through (body copy / CTA)",
        "convert": "conversion (offer / pricing)",
    }
    for stage, label in labels.items():
        raw = summary["raw"].get(stage)
        bench = base.get(stage)
        if raw is None or bench is None:
            continue
        if raw < bench * 0.7:
            findings.append(
                f"{label}: simulated {raw:.1%} vs ~{bench:.0%} benchmark — "
                "this is the biggest leak; fix here first."
            )

    segments = segment_breakdown(store, audience, stimulus_id)
    styles = [s for s in segments if s["dimension"] == "objection_style" and s["n"] >= 5]
    if styles:
        worst = min(styles, key=lambda s: s["engaged_rate"])
        best = max(styles, key=lambda s: s["engaged_rate"])
        if best["engaged_rate"] > 0 and worst["engaged_rate"] < best["engaged_rate"] * 0.5:
            findings.append(
                f"'{worst['segment']}' personas engage at {worst['engaged_rate']:.0%} "
                f"vs {best['engaged_rate']:.0%} for '{best['segment']}' — the message "
                "isn't answering the skeptical read."
            )
        angry = [s for s in styles if s["annoyed_rate"] > 0.1]
        for s in angry:
            findings.append(
                f"'{s['segment']}' personas show {s['annoyed_rate']:.0%} annoyance "
                "(unsubscribe/report) — brand-damage risk with this copy."
            )
    return findings
