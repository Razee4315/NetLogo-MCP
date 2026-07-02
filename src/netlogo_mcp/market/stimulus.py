"""Stimulus ingestion — normalize campaign artifacts into ``Stimulus``.

v1: structured YAML / pasted copy (zero parsing risk).
v2: email/landing-page HTML via BeautifulSoup + html2text.
v3 (future): image ads described by a vision model — see plan.md §7.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .config import get_campaigns_dir
from .schemas import CampaignSpec, ChannelParams, Stimulus

# ── v1: builders ─────────────────────────────────────────────────────────────


def email_stimulus(
    id: str,
    subject: str,
    body_text: str,
    cta: str,
    sender: str = "",
    preheader: str = "",
    offer: str | None = None,
    price_shown: str | None = None,
    variant_of: str | None = None,
    channel_params: ChannelParams | None = None,
) -> Stimulus:
    teaser = {"subject": subject}
    if sender:
        teaser["sender"] = sender
    if preheader:
        teaser["preheader"] = preheader
    return Stimulus(
        id=id,
        variant_of=variant_of,
        type="email",
        teaser=teaser,
        body_text=body_text,
        cta=cta,
        offer=offer,
        price_shown=price_shown,
        channel_params=channel_params or ChannelParams(channel="email"),
    )


def social_ad_stimulus(
    id: str,
    headline: str,
    body_text: str,
    cta: str,
    thumbnail_description: str = "",
    offer: str | None = None,
    price_shown: str | None = None,
    variant_of: str | None = None,
    channel_params: ChannelParams | None = None,
) -> Stimulus:
    teaser = {"headline": headline}
    if thumbnail_description:
        teaser["thumbnail"] = thumbnail_description
    return Stimulus(
        id=id,
        variant_of=variant_of,
        type="social_ad",
        teaser=teaser,
        body_text=body_text,
        cta=cta,
        offer=offer,
        price_shown=price_shown,
        visual_description=thumbnail_description or None,
        channel_params=channel_params or ChannelParams(channel="paid_social"),
    )


# ── v2: HTML ingestion ───────────────────────────────────────────────────────


def _clean_text(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def stimulus_from_html(
    id: str,
    html: str,
    type: str = "email",
    subject: str = "",
    sender: str = "",
    cta: str = "",
    variant_of: str | None = None,
) -> Stimulus:
    """Extract readable copy from an HTML email or landing page.

    The subject/sender of an email live in its headers, not the HTML — pass
    them explicitly. When ``cta`` is omitted, the most prominent link/button
    text is used.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head", "noscript"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""

    # CTA heuristic: button-ish elements, then short prominent links.
    found_cta = cta
    if not found_cta:
        candidates: list[str] = []
        for el in soup.find_all(["button", "a"]):
            txt = el.get_text(" ", strip=True)
            classes = " ".join(el.get("class", []))
            if not txt or len(txt) > 60:
                continue
            if el.name == "button" or re.search(r"btn|button|cta", classes, re.I):
                candidates.insert(0, txt)
            elif re.search(
                r"\b(get|start|claim|try|buy|shop|join|sign|order|book|download)\b",
                txt,
                re.I,
            ):
                candidates.append(txt)
        found_cta = candidates[0] if candidates else ""

    import html2text

    converter = html2text.HTML2Text()
    converter.ignore_images = True
    converter.ignore_links = True
    converter.body_width = 0
    body = _clean_text(converter.handle(str(soup)))

    # Price detection for the hidden-price distrust signal.
    price_match = re.search(
        r"(?:[$€£]\s?\d+(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?\s?(?:USD|EUR|GBP))"
        r"(?:\s?/\s?(?:mo|month|yr|year|week|wk))?",
        body,
    )

    teaser: dict[str, str] = {}
    if type == "email":
        teaser["subject"] = subject or title
        if sender:
            teaser["sender"] = sender
    else:
        teaser["headline"] = subject or title or body.split("\n", 1)[0][:80]

    return Stimulus(
        id=id,
        variant_of=variant_of,
        type=type,  # type: ignore[arg-type]
        teaser=teaser,
        body_text=body[:4000],
        cta=found_cta,
        price_shown=price_match.group(0) if price_match else None,
        channel_params=ChannelParams(
            channel="email" if type == "email" else "paid_social"
        ),
    )


# ── Campaign spec persistence ────────────────────────────────────────────────


def load_campaign_spec(source: str) -> CampaignSpec:
    """Parse a CampaignSpec from YAML/JSON text or a path to a file."""
    text = source
    if "\n" not in source and (
        source.endswith((".yaml", ".yml", ".json")) or "/" in source or "\\" in source
    ):
        p = Path(source)
        if not p.is_file():
            raise FileNotFoundError(f"campaign spec file not found: {source}")
        text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("campaign spec must be a mapping")
    return CampaignSpec(**data)


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()) or "campaign"


def save_campaign_spec(spec: CampaignSpec) -> str:
    path = get_campaigns_dir() / f"{_slug(spec.name)}.json"
    path.write_text(spec.model_dump_json(indent=1), encoding="utf-8")
    return str(path)


def load_saved_campaign(name: str) -> CampaignSpec:
    path = get_campaigns_dir() / f"{_slug(name)}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"campaign '{name}' not found — expected {path}. "
            "Use create_campaign first."
        )
    return CampaignSpec(**json.loads(path.read_text(encoding="utf-8")))


def list_campaigns() -> list[dict[str, Any]]:
    out = []
    for p in sorted(get_campaigns_dir().glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(
                {
                    "name": data.get("name", p.stem),
                    "audience": data.get("audience", "?"),
                    "variants": [s.get("id") for s in data.get("stimuli", [])],
                    "file": str(p),
                }
            )
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return out
