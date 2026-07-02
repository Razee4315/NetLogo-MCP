"""Pre-flight report — the actual product of a campaign run.

``generate_report`` collects analytics into one data dict, renders a
markdown report (primary artifact, returned to the MCP client) and an HTML
report with interactive plotly charts (written to ``market_data/reports``).
"""

from __future__ import annotations

import html as html_mod
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Template

from . import analytics
from .calibration import Calibration, load_base_rates
from .config import get_reports_dir

if TYPE_CHECKING:
    from .schemas import Audience, CampaignSpec
    from .store import EventStore

# ── Data collection ──────────────────────────────────────────────────────────


def build_report_data(
    campaign: CampaignSpec,
    audience: Audience,
    store: EventStore,
    calibration: Calibration | None = None,
) -> dict[str, Any]:
    calibration = calibration or Calibration.load()
    channel_by_variant = {
        s.id: s.channel_params.channel for s in campaign.stimuli
    }
    runs = store.runs_df()
    engines = sorted(set(runs["engine"])) if len(runs) else []
    heuristic = any("Heuristic" in e for e in engines)

    funnel = analytics.funnel_summary(
        store, audience, calibration, channel_by_variant
    )
    variants: dict[str, Any] = {}
    for stim in campaign.stimuli:
        if stim.id not in funnel:
            continue
        variants[stim.id] = {
            "teaser": stim.teaser_text(),
            "channel": stim.channel_params.channel,
            "funnel": funnel[stim.id],
            "benchmark": load_base_rates().get(
                stim.channel_params.channel, {}
            ),
            "objections": analytics.mine_objections(store, stim.id),
            "wom": analytics.wom_stats(store, stim.id),
            "weak_points": analytics.weak_points(
                store, audience, stim.id, stim.channel_params.channel
            ),
            "segments": analytics.segment_breakdown(store, audience, stim.id),
        }

    return {
        "campaign": campaign.name,
        "audience": audience.spec.name,
        "audience_size": audience.size,
        "product_context": audience.spec.product_context,
        "fidelity": campaign.fidelity,
        "replicates": campaign.replicates,
        "engines": engines,
        "heuristic_mode": heuristic,
        "calibrated": not calibration.is_identity(),
        "total_llm_calls": int(runs["llm_calls"].sum()) if len(runs) else 0,
        "variants": variants,
        "comparisons": analytics.compare_variants(store, audience),
        "generated": time.strftime("%Y-%m-%d %H:%M"),
    }


# ── Markdown ─────────────────────────────────────────────────────────────────

_MD_TEMPLATE = Template(
    """# Pre-Flight Report — {{ campaign }}

**Audience:** {{ audience }} ({{ audience_size }} personas{% if product_context %}, shopping for {{ product_context }}{% endif %})
**Setup:** {{ replicates }} replicate(s), fidelity `{{ fidelity }}`, engine(s): {{ engines | join(', ') }} — {{ total_llm_calls }} cognition calls
**Generated:** {{ generated }}

{% if heuristic_mode -%}
> ⚠️ **Heuristic cognition** — reactions come from the deterministic rule
> backend, not a live LLM. Set `SYNTH_LLM_MODE=live` (with Ollama running)
> for persona-driven verbatims and richer differentiation. Relative
> comparisons remain meaningful; treat verbatims as placeholders.
{%- endif %}

{% for vid, v in variants.items() %}
## Variant `{{ vid }}` ({{ v.channel }})

> {{ v.teaser | replace('\n', ' · ') }}

### Funnel

| stage | simulated (95% CI) | {% if calibrated %}calibrated | {% endif %}benchmark |
|---|---|{% if calibrated %}---|{% endif %}---|
| reach | {{ "%.1f%%"|format(100 * v.funnel.metrics.reach.mean) }} ({{ "%.1f"|format(100 * v.funnel.metrics.reach.lo) }}–{{ "%.1f"|format(100 * v.funnel.metrics.reach.hi) }}) | {% if calibrated %}— | {% endif %}— |
| attention gate | {{ "%.1f%%"|format(100 * v.funnel.metrics.gate.mean) }} ({{ "%.1f"|format(100 * v.funnel.metrics.gate.lo) }}–{{ "%.1f"|format(100 * v.funnel.metrics.gate.hi) }}) | {% if calibrated %}{{ "%.1f%%"|format(100 * v.funnel.calibrated.gate) }} | {% endif %}{{ "%.0f%%"|format(100 * v.benchmark.get('gate', 0)) }} |
| click-through | {{ "%.1f%%"|format(100 * v.funnel.metrics.click.mean) }} ({{ "%.1f"|format(100 * v.funnel.metrics.click.lo) }}–{{ "%.1f"|format(100 * v.funnel.metrics.click.hi) }}) | {% if calibrated %}{{ "%.1f%%"|format(100 * v.funnel.calibrated.click) }} | {% endif %}{{ "%.0f%%"|format(100 * v.benchmark.get('click', 0)) }} |
| conversion | {{ "%.1f%%"|format(100 * v.funnel.metrics.convert.mean) }} ({{ "%.1f"|format(100 * v.funnel.metrics.convert.lo) }}–{{ "%.1f"|format(100 * v.funnel.metrics.convert.hi) }}) | {% if calibrated %}{{ "%.1f%%"|format(100 * v.funnel.calibrated.convert) }} | {% endif %}{{ "%.0f%%"|format(100 * v.benchmark.get('convert', 0)) }} |
| **audience conversion** | **{{ "%.2f%%"|format(100 * v.funnel.metrics.conversion_of_audience.mean) }}** | {% if calibrated %}— | {% endif %}— |
| annoyance | {{ "%.1f%%"|format(100 * v.funnel.metrics.annoyance.mean) }} | {% if calibrated %}— | {% endif %}— |

### Word of mouth

{{ v.wom.sharers }} sharer(s) generated {{ v.wom.social_exposures }} social exposures
({{ v.wom.amplification }}x amplification over {{ v.wom.direct_exposures }} direct).
{%- if v.wom.social_exposures > 0 %}
Social exposures converted at {{ "%.1f%%"|format(100 * v.wom.social_conversion_rate) }} vs {{ "%.1f%%"|format(100 * v.wom.direct_conversion_rate) }} direct.
{%- endif %}

### Top objections

{% for o in v.objections[:5] -%}
- **{{ o.theme }}** ({{ o.count }} mentions) — e.g. “{{ o.quotes[0] }}”
{% endfor %}
{%- if not v.objections %}_No objections recorded._{% endif %}

### Weak points

{% for w in v.weak_points -%}
- {{ w }}
{% endfor %}
{%- if not v.weak_points %}_No major leaks vs benchmark._{% endif %}

### Segments (objection style)

| segment | n | engaged | clicked | converted | annoyed | sentiment |
|---|---|---|---|---|---|---|
{% for s in v.segments if s.dimension == 'objection_style' -%}
| {{ s.segment }} | {{ s.n }} | {{ "%.0f%%"|format(100 * s.engaged_rate) }} | {{ "%.0f%%"|format(100 * s.click_rate) }} | {{ "%.1f%%"|format(100 * s.conversion_rate) }} | {{ "%.0f%%"|format(100 * s.annoyed_rate) }} | {{ "%+.2f"|format(s.mean_sentiment) }} |
{% endfor %}

{% endfor %}
{% if comparisons %}
## A/B verdict

| metric | A | B | rate A | rate B | winner | p-value |
|---|---|---|---|---|---|---|
{% for c in comparisons -%}
| {{ c.metric }} | {{ c.variant_a }} | {{ c.variant_b }} | {{ "%.2f%%"|format(100 * c.rate_a) }} | {{ "%.2f%%"|format(100 * c.rate_b) }} | **{{ c.winner }}**{{ " ✓" if c.significant else " (n.s.)" }} | {{ c.p_value }} |
{% endfor %}

_✓ = significant at p<0.05 (two-proportion z-test, pooled replicates). "n.s." differences are directional only — add replicates to tighten._
{% endif %}

---
_How to read this: **relative** results (variant ranking, segment ranking,
objection themes) are the trustworthy part. **Absolute** rates are simulated
{% if calibrated %}and calibrated to your benchmarks{% else %}and NOT yet
calibrated — run `calibrate` with real campaign stats before trusting
levels{% endif %}. A synthetic audience is a rehearsal, not the market._
"""
)


def render_markdown(data: dict[str, Any]) -> str:
    return _MD_TEMPLATE.render(**data)


# ── HTML (plotly) ────────────────────────────────────────────────────────────


def _funnel_figure(data: dict[str, Any]):
    import plotly.graph_objects as go

    stages = ["reach", "gate", "click", "convert"]
    labels = ["reach", "attention gate", "click-through", "conversion"]
    fig = go.Figure()
    for vid, v in data["variants"].items():
        fig.add_trace(
            go.Bar(
                name=vid,
                x=labels,
                y=[100 * v["funnel"]["metrics"][s]["mean"] for s in stages],
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "array": [
                        100
                        * (
                            v["funnel"]["metrics"][s]["hi"]
                            - v["funnel"]["metrics"][s]["mean"]
                        )
                        for s in stages
                    ],
                    "arrayminus": [
                        100
                        * (
                            v["funnel"]["metrics"][s]["mean"]
                            - v["funnel"]["metrics"][s]["lo"]
                        )
                        for s in stages
                    ],
                },
            )
        )
    fig.update_layout(
        title="Funnel by variant (%)",
        barmode="group",
        yaxis_title="% of previous stage",
        template="plotly_white",
        height=420,
    )
    return fig


def _segment_figure(data: dict[str, Any]):
    import plotly.graph_objects as go

    dims = ("objection_style", "income", "age_bracket")
    variants = list(data["variants"])
    seg_lookup: dict[str, dict[str, float]] = {}
    for vid, v in data["variants"].items():
        for s in v["segments"]:
            if s["dimension"] in dims:
                key = f"{s['dimension'].replace('_', ' ')}: {s['segment']}"
                seg_lookup.setdefault(key, {})[vid] = 100 * s["engaged_rate"]
    rows = sorted(seg_lookup)
    z = [[seg_lookup[r].get(vid, 0.0) for vid in variants] for r in rows]
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=variants,
            y=rows,
            colorscale="YlGnBu",
            colorbar={"title": "engaged %"},
        )
    )
    fig.update_layout(
        title="Engagement rate by segment (%)",
        template="plotly_white",
        height=max(360, 22 * len(rows) + 120),
    )
    return fig


def render_html(data: dict[str, Any]) -> str:
    """Standalone HTML: markdown content (escaped, minimally styled) plus
    interactive charts."""
    md = render_markdown(data)
    md_html = _markdown_to_html(md)
    try:
        funnel_div = _funnel_figure(data).to_html(
            full_html=False, include_plotlyjs="cdn"
        )
        segment_div = _segment_figure(data).to_html(
            full_html=False, include_plotlyjs=False
        )
    except Exception:  # charts are enhancement, never a blocker
        funnel_div = segment_div = ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Pre-Flight — {html_mod.escape(data['campaign'])}</title>
<style>
 body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 960px;
        margin: 2rem auto; padding: 0 1rem; color: #1a202c; line-height: 1.55; }}
 table {{ border-collapse: collapse; margin: 0.8rem 0; }}
 th, td {{ border: 1px solid #cbd5e0; padding: 4px 10px; font-size: 0.92rem; }}
 th {{ background: #edf2f7; }}
 blockquote {{ border-left: 4px solid #a0aec0; margin: 0.6rem 0;
              padding: 0.2rem 0.9rem; color: #4a5568; background: #f7fafc; }}
 code {{ background: #edf2f7; padding: 0 4px; border-radius: 3px; }}
 h1, h2 {{ border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }}
</style></head>
<body>
{funnel_div}
{segment_div}
{md_html}
</body></html>"""


def _markdown_to_html(md: str) -> str:
    """Small dependency-free markdown subset renderer (headers, tables,
    bold/italic/code, blockquotes, lists, hr)."""
    out: list[str] = []
    in_table = False
    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                continue  # separator row
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table>")
                in_table = True
            row = "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells)
            out.append(f"<tr>{row}</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if not stripped:
            out.append("")
        elif stripped.startswith("### "):
            out.append(f"<h3>{_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            out.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            out.append(f"<h1>{_inline(stripped[2:])}</h1>")
        elif stripped.startswith("> "):
            out.append(f"<blockquote>{_inline(stripped[2:])}</blockquote>")
        elif stripped.startswith("- "):
            out.append(f"<li>{_inline(stripped[2:])}</li>")
        elif stripped == "---":
            out.append("<hr>")
        else:
            out.append(f"<p>{_inline(stripped)}</p>")
    if in_table:
        out.append("</table>")
    return "\n".join(out)


def _inline(text: str) -> str:
    text = html_mod.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"_(.+?)_", r"<em>\1</em>", text)
    return text


# ── Entry point ──────────────────────────────────────────────────────────────


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()) or "report"


def generate_report(
    campaign: CampaignSpec,
    audience: Audience,
    store: EventStore,
    calibration: Calibration | None = None,
) -> dict[str, str]:
    """Build + persist both report formats. Returns paths and the markdown."""
    data = build_report_data(campaign, audience, store, calibration)
    md = render_markdown(data)
    html = render_html(data)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = get_reports_dir() / f"{_slug(campaign.name)}_{stamp}"
    md_path = Path(f"{base}.md")
    html_path = Path(f"{base}.html")
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    return {
        "markdown": md,
        "markdown_path": str(md_path),
        "html_path": str(html_path),
    }
