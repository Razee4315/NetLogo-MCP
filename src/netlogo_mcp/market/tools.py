"""MCP tools for the market simulation (SynthAudience).

Registered on the same FastMCP server as the core NetLogo tools — importing
this module (see ``netlogo_mcp.server``) is what registers them.

Typical conversational flow:

    generate_audience -> create_campaign -> run_campaign
        -> get_campaign_report -> interview_persona -> calibrate
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError

from ..config import get_models_dir
from ..server import mcp
from . import analytics as _analytics
from . import personas as _personas
from . import stimulus as _stimulus
from .archetypes import archetype_summary, assign_archetypes
from .calibration import Calibration, fit_from_csv
from .cognition import CognitionEngine
from .config import get_llm_config
from .orchestrator import run_campaign as _run_campaign
from .report import generate_report
from .store import EventStore
from .worlds import NetLogoWorld, PythonWorld

if TYPE_CHECKING:
    from .schemas import Audience, CampaignSpec


def _load_audience_or_fail(name: str) -> Audience:
    try:
        return _personas.load_audience(name)
    except FileNotFoundError as exc:
        raise ToolError(str(exc)) from exc


def _load_campaign_or_fail(name: str) -> CampaignSpec:
    try:
        return _stimulus.load_saved_campaign(name)
    except FileNotFoundError as exc:
        raise ToolError(str(exc)) from exc


async def _progress(ctx: Context, message: str) -> None:
    try:
        await ctx.info(message)
    except Exception:  # progress must never fail a run
        pass


# ── Audience tools ───────────────────────────────────────────────────────────


@mcp.tool()
async def generate_audience(spec_yaml: str, ctx: Context) -> str:
    """Generate and save a synthetic audience from a YAML spec.

    The audience is a frozen, seeded population of personas plus a social
    network — the same spec always produces the same people, so campaign
    variants can be tested against an identical audience.

    Args:
        spec_yaml: YAML audience spec. Minimal example:

            name: saas-founders
            product_context: "a churn-analytics SaaS tool"
            size: 300
            seed: 42
            distributions:
              age: {mean: 33, sd: 8, min: 22, max: 60}
              income_bracket: {low: 0.2, mid: 0.5, high: 0.3}
              trust_in_ads: {mean: 0.2, sd: 0.1}
            network:
              topology: watts-strogatz   # or barabasi-albert (influencer-heavy)
              k: 8

        Any persona field may appear in `distributions` (categorical weights
        or {mean, sd, min, max}); unlisted fields use sensible consumer
        defaults. Optional `conditionals` add correlations between fields.

    Returns:
        Archetype summary of the generated population.
    """
    try:
        spec = _personas.load_spec(spec_yaml)
    except Exception as exc:
        raise ToolError(f"Invalid audience spec: {exc}") from exc

    await _progress(ctx, f"sampling {spec.size} personas for '{spec.name}' ...")
    audience = _personas.generate_audience(spec)
    audience = assign_archetypes(audience)
    path = _personas.save_audience(audience)

    lines = [
        f"Audience **{spec.name}** generated: {audience.size} personas, "
        f"{sum(len(n) for n in audience.edges) // 2} social ties "
        f"({spec.network.topology}). Saved to `{path}`.",
        "",
        "| archetype | label | size | distinctive traits |",
        "| --- | --- | --- | --- |",
    ]
    for a in archetype_summary(audience):
        lines.append(
            f"| {a['archetype']} | {a['label']} | {a['size']} | "
            f"{'; '.join(a['distinctive']) or '-'} |"
        )
    lines.append("")
    lines.append(
        f"Next: `create_campaign` with `audience: {spec.name}`, then `run_campaign`."
    )
    return "\n".join(lines)


@mcp.tool()
async def list_audiences(ctx: Context) -> str:
    """List saved synthetic audiences."""
    items = _personas.list_audiences()
    if not items:
        return "No audiences yet — use generate_audience with a YAML spec."
    lines = ["| name | size | product context |", "| --- | --- | --- |"]
    for a in items:
        lines.append(f"| {a['name']} | {a['size']} | {a['product_context']} |")
    return "\n".join(lines)


@mcp.tool()
async def get_audience(name: str, ctx: Context, sample: int = 3) -> str:
    """Show a saved audience: spec summary, archetypes, and sample persona
    cards.

    Args:
        name: Audience name (see list_audiences).
        sample: How many example persona cards to include (0-10).
    """
    audience = _load_audience_or_fail(name)
    spec = audience.spec
    lines = [
        f"**{spec.name}** — {audience.size} personas, seed {spec.seed}",
        f"Product context: {spec.product_context or '(none)'}",
        f"Network: {spec.network.topology}, mean degree {spec.network.k}",
        "",
        "| archetype | label | size |",
        "| --- | --- | --- |",
    ]
    for a in archetype_summary(audience):
        lines.append(f"| {a['archetype']} | {a['label']} | {a['size']} |")
    for p in audience.personas[: max(0, min(10, sample))]:
        lines += ["", f"**{p.id}** ({p.objection_style}):", f"> {p.persona_card}"]
    return "\n".join(lines)


# ── Campaign tools ───────────────────────────────────────────────────────────


@mcp.tool()
async def create_campaign(campaign_yaml: str, ctx: Context) -> str:
    """Create and save a campaign (one audience x one or more ad/email
    variants).

    Args:
        campaign_yaml: YAML campaign spec. Example:

            name: launch-email
            audience: saas-founders
            replicates: 3          # runs per variant (confidence intervals)
            max_ticks: 72          # 1 tick = 1 simulated hour
            fidelity: mixed        # fast | mixed | full (LLM cost vs detail)
            stimuli:
              - id: A
                type: email        # email | social_ad | landing_page | search_ad
                teaser:
                  subject: "Your churn number is hiding in plain sight"
                  sender: "Ada from RetainIQ"
                body_text: "..."
                cta: "See your churn breakdown"
                price_shown: "$49/mo"
                channel_params: {channel: email, send_tick: 1, reach: 1.0}
              - id: B
                variant_of: A
                type: email
                teaser: {subject: "Cut churn 20% this quarter"}
                body_text: "..."
                cta: "Start free trial"

    Returns:
        Validation summary; run it with run_campaign.
    """
    try:
        spec = _stimulus.load_campaign_spec(campaign_yaml)
    except Exception as exc:
        raise ToolError(f"Invalid campaign spec: {exc}") from exc
    _load_audience_or_fail(spec.audience)  # fail fast on missing audience
    path = _stimulus.save_campaign_spec(spec)
    variants = ", ".join(s.id for s in spec.stimuli)
    return (
        f"Campaign **{spec.name}** saved to `{path}`.\n"
        f"- audience: {spec.audience}\n"
        f"- variants: {variants}\n"
        f"- {spec.replicates} replicate(s) x {spec.max_ticks} ticks, "
        f"fidelity `{spec.fidelity}`\n\n"
        f'Run it: run_campaign("{spec.name}")'
    )


@mcp.tool()
async def list_campaigns(ctx: Context) -> str:
    """List saved campaigns."""
    items = _stimulus.list_campaigns()
    if not items:
        return "No campaigns yet — use create_campaign."
    lines = ["| name | audience | variants |", "| --- | --- | --- |"]
    for c in items:
        lines.append(f"| {c['name']} | {c['audience']} | {', '.join(c['variants'])} |")
    return "\n".join(lines)


async def _netlogo_world_factory(ctx: Context):
    """Build a NetLogoWorld wired to the shared workspace."""
    # Imported lazily: core tools also import the server module at import
    # time, so a module-level import here would be circular.
    from ..tools import (
        _ensure_netlogo,
        _jvm_call,
        _nlogox_version,
        _polish_gui_window,
        _set_current_model_path,
        _wrap_netlogo_error,
        _wrap_nlogox,
    )

    nl = await _ensure_netlogo(ctx)

    async def command(cmd: str) -> None:
        try:
            await _jvm_call(ctx, nl.command, cmd)
        except Exception as e:  # readable errors instead of Java traces
            raise _wrap_netlogo_error(e) from e

    async def report(reporter: str) -> Any:
        try:
            return await _jvm_call(ctx, nl.report, reporter)
        except Exception as e:
            raise _wrap_netlogo_error(e) from e

    async def load_model(code: str, widgets: list[dict[str, Any]] | None) -> None:
        xml = _wrap_nlogox(code, _nlogox_version(ctx), widgets=widgets)
        path = get_models_dir() / "market_sim.nlogox"
        path.write_text(xml, encoding="utf-8")
        try:
            await _jvm_call(ctx, nl.load_model, str(path).replace("\\", "/"))
        except Exception as e:
            raise _wrap_netlogo_error(e) from e
        _set_current_model_path(ctx, path)
        _polish_gui_window("NetLogo — market_sim")

    def factory() -> NetLogoWorld:
        return NetLogoWorld(command, report, load_model)

    return factory


@mcp.tool()
async def run_campaign(
    campaign_name: str,
    ctx: Context,
    engine: str = "netlogo",
    watch: bool = False,
) -> str:
    """Run a saved campaign against its audience and log every reaction.

    Runs every variant x replicate with a PAIRED design (identical audience,
    reach and network randomness per replicate across variants), so A/B
    differences are attributable to the creative.

    Cognition: personas react via the configured backend — a live local LLM
    when SYNTH_LLM_MODE=live (Ollama etc.), otherwise the deterministic
    heuristic model.

    Args:
        campaign_name: A campaign saved with create_campaign.
        engine: "netlogo" (visible simulation in the NetLogo window; first
            call boots the JVM, 30-60s) or "python" (headless, fastest).
        watch: Slow the NetLogo run down (~0.15s/tick) to watch the campaign
            spread through the network live. Ignored for engine="python".

    Returns:
        Run summary per variant; then call get_campaign_report.
    """
    if engine not in ("netlogo", "python"):
        raise ToolError('engine must be "netlogo" or "python"')
    campaign = _load_campaign_or_fail(campaign_name)
    audience = _load_audience_or_fail(campaign.audience)

    if engine == "netlogo":
        world_factory = await _netlogo_world_factory(ctx)
    else:
        world_factory = PythonWorld

    cfg = get_llm_config()
    await _progress(
        ctx,
        f"running '{campaign.name}': {len(campaign.stimuli)} variant(s) x "
        f"{campaign.replicates} replicate(s) on {engine}, cognition="
        f"{cfg.mode} ...",
    )

    store = EventStore(campaign.name)
    try:
        summary = await _run_campaign(
            campaign,
            audience,
            world_factory=world_factory,
            store=store,
            on_progress=lambda m: _progress(ctx, m),
            tick_delay_s=0.15 if (watch and engine == "netlogo") else 0.0,
        )
    finally:
        store.close()

    lines = [
        f"Campaign **{campaign.name}** complete "
        f"({summary['total_llm_calls']} cognition calls, engine {engine}, "
        f"cognition mode `{cfg.mode}`).",
        "",
        "| variant | replicate | ticks | converted | clicked | ignored | annoyed |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in summary["runs"]:
        c = r["final_counts"]
        lines.append(
            f"| {r['stimulus_id']} | {r['replicate']} | {r['ticks']} | "
            f"{c.get('converted', 0)} | {c.get('clicked', 0)} | "
            f"{c.get('ignored', 0)} | {c.get('annoyed', 0)} |"
        )
    lines += ["", f'Full analysis: get_campaign_report("{campaign.name}")']
    if cfg.mode == "mock":
        lines.append(
            "_Note: cognition ran on the heuristic backend (no LLM). Set "
            "SYNTH_LLM_MODE=live once a local model is installed._"
        )
    return "\n".join(lines)


@mcp.tool()
async def get_campaign_report(campaign_name: str, ctx: Context) -> str:
    """Generate the pre-flight report for a campaign that has been run.

    Includes: funnel with confidence intervals (simulated / calibrated /
    industry benchmark), segment breakdown, top objections with verbatim
    quotes, word-of-mouth stats, weak-point diagnosis, and the A/B verdict.
    Also writes an HTML version with interactive charts.

    Args:
        campaign_name: A campaign previously executed with run_campaign.
    """
    campaign = _load_campaign_or_fail(campaign_name)
    audience = _load_audience_or_fail(campaign.audience)
    store = EventStore(campaign.name)
    try:
        if not store.completed_run_ids():
            raise ToolError(
                f"No completed runs for '{campaign_name}' — use run_campaign first."
            )
        result = generate_report(campaign, audience, store)
    finally:
        store.close()
    return (
        result["markdown"] + f"\n\n_HTML report with charts: `{result['html_path']}`_"
    )


@mcp.tool()
async def compare_campaign_variants(campaign_name: str, ctx: Context) -> str:
    """Paired A/B comparison of a campaign's variants (winner, lift,
    significance). Subset of get_campaign_report for quick checks.

    Args:
        campaign_name: A campaign previously executed with run_campaign.
    """
    campaign = _load_campaign_or_fail(campaign_name)
    audience = _load_audience_or_fail(campaign.audience)
    store = EventStore(campaign.name)
    try:
        comparisons = _analytics.compare_variants(store, audience)
    finally:
        store.close()
    if not comparisons:
        raise ToolError("No completed runs (or only one variant) — nothing to compare.")
    lines = [
        "| metric | A | B | rate A | rate B | winner | p |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in comparisons:
        sig = " ✓" if c["significant"] else " (n.s.)"
        lines.append(
            f"| {c['metric']} | {c['variant_a']} | {c['variant_b']} | "
            f"{c['rate_a']:.2%} | {c['rate_b']:.2%} | "
            f"**{c['winner']}**{sig} | {c['p_value']} |"
        )
    return "\n".join(lines)


# ── Focus group & calibration ────────────────────────────────────────────────


@mcp.tool()
async def interview_persona(
    audience_name: str,
    question: str,
    ctx: Context,
    persona_id: str | None = None,
    n: int = 1,
) -> str:
    """Ask a follow-up question to persona(s) — an on-demand focus group.

    Args:
        audience_name: A saved audience.
        question: What to ask, e.g. "What would make you trust this brand
            enough to click?"
        persona_id: Ask one specific persona (id from get_audience). When
            omitted, a stratified handful is asked instead.
        n: How many personas to ask when persona_id is omitted (1-10).
    """
    audience = _load_audience_or_fail(audience_name)
    engine = CognitionEngine(audience)

    if persona_id is not None:
        indices = [i for i, p in enumerate(audience.personas) if p.id == persona_id]
        if not indices:
            raise ToolError(f"persona '{persona_id}' not found in {audience_name}")
    else:
        from .archetypes import representative_indices

        indices = representative_indices(
            audience, max(1, min(10, n)), seed=len(question)
        )

    blocks = []
    for i in indices:
        p = audience.personas[i]
        answer = await engine.interview(i, question)
        blocks.append(
            f"**{p.id}** ({p.age}, {p.occupation}, {p.objection_style}):\n"
            f"> {answer.strip()}"
        )
    mode = get_llm_config().mode
    note = (
        "\n\n_Heuristic backend — interviews get much richer with SYNTH_LLM_MODE=live._"
        if mode == "mock"
        else ""
    )
    return f"**Q: {question}**\n\n" + "\n\n".join(blocks) + note


@mcp.tool()
async def calibrate(
    ctx: Context,
    channel: str = "email",
    campaign_name: str | None = None,
    csv_path: str | None = None,
) -> str:
    """Calibrate simulated funnel rates to real-world levels.

    Two modes:
    - With `csv_path`: fit against a REAL past campaign's stats. The CSV
      needs columns `sent, opened, clicked, converted` (one or more rows).
      Requires `campaign_name` for the simulated side of the fit.
    - Without `csv_path`: anchor the campaign's simulated rates to industry
      benchmark base rates (a sane default until you have real data).

    After calibrating, get_campaign_report shows a calibrated column.

    Args:
        channel: email | paid_social | organic.
        campaign_name: Campaign whose simulated rates to calibrate from.
        csv_path: Optional real campaign stats CSV.
    """
    if campaign_name is None:
        raise ToolError("campaign_name is required — run a campaign first.")
    campaign = _load_campaign_or_fail(campaign_name)
    audience = _load_audience_or_fail(campaign.audience)
    store = EventStore(campaign.name)
    try:
        funnel = _analytics.funnel_summary(store, audience)
    finally:
        store.close()
    if not funnel:
        raise ToolError(f"No completed runs for '{campaign_name}'.")
    # Average raw stage rates across variants for the fit.
    simulated = {
        stage: float(sum(v["raw"][stage] for v in funnel.values()) / len(funnel))
        for stage in ("gate", "click", "convert")
    }

    if csv_path:
        p = Path(csv_path)
        if not p.is_file():
            raise ToolError(f"CSV not found: {csv_path}")
        try:
            cal = fit_from_csv(str(p), channel, simulated)
        except Exception as exc:
            raise ToolError(f"Calibration failed: {exc}") from exc
        source = f"real campaign stats ({p.name})"
    else:
        cal = Calibration.load()
        cal.fit_to_base_rates(channel, simulated)
        cal.save()
        source = "industry benchmark base rates"

    fitted = cal.apply_funnel(channel, simulated)
    lines = [
        f"Calibration fitted for **{channel}** from {source} "
        f"(saved {datetime.now():%Y-%m-%d %H:%M}).",
        "",
        "| stage | simulated | calibrated |",
        "| --- | --- | --- |",
    ]
    for stage in ("gate", "click", "convert"):
        lines.append(f"| {stage} | {simulated[stage]:.1%} | {fitted[stage]:.1%} |")
    lines.append("\nRe-run get_campaign_report to see calibrated numbers.")
    return "\n".join(lines)


@mcp.tool()
async def market_info(ctx: Context) -> str:
    """Status of the market-simulation module: LLM config, saved audiences,
    campaigns, and where artifacts live."""
    from .config import get_market_data_dir

    cfg = get_llm_config()
    audiences = _personas.list_audiences()
    campaigns = _stimulus.list_campaigns()
    cal = Calibration.load()
    return json.dumps(
        {
            "cognition": {
                "mode": cfg.mode,
                "endpoint": cfg.base_url if cfg.mode == "live" else None,
                "model": cfg.model if cfg.mode == "live" else "heuristic backend",
                "hint": (
                    "set SYNTH_LLM_MODE=live with Ollama running to enable "
                    "LLM cognition"
                    if cfg.mode == "mock"
                    else "live"
                ),
            },
            "audiences": [a["name"] for a in audiences],
            "campaigns": [c["name"] for c in campaigns],
            "calibrated_channels": sorted(cal.maps),
            "data_dir": str(get_market_data_dir()),
        },
        indent=1,
    )
