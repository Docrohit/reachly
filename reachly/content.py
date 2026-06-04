"""Content generation: turn a BusinessProfile into a daily thought-leadership post.

The agent rotates through the business's content themes day by day, asks the LLM
for a structured post (hook + body + hashtags + image prompt), and returns a
GeneratedPost that platform adapters can render.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from .context import StrategyContext
from .llm import LLMClient
from .models import BusinessProfile, GeneratedPost

logger = logging.getLogger("reachly.content")

SYSTEM_PROMPT = """You are a senior social-media ghostwriter and brand strategist.
You write posts that position a founder/business as a credible THOUGHT LEADER in
their sector — not as an ad. You write in the requested brand voice, sound human,
avoid cliches and empty hype, and never use emoji spam. Posts must give real,
specific value (an insight, a lesson, a contrarian take, a useful framework) and
only softly tie back to the business. Output ONLY valid JSON, no markdown fences."""

USER_PROMPT_TEMPLATE = """Write ONE original post for today.

BUSINESS:
- Name: {name}
- Sector: {sector}
- Vision: {vision}
- Product/Service: {product_info}
- Website: {website}
- Brand voice: {voice}
- Language: {language}

TODAY'S THEME (write about this angle): {theme}
{strategy_block}
{recent_block}
Requirements:
- A scroll-stopping one-line "hook".
- A "body" of 90-160 words: valuable, specific, story- or insight-driven.
  Thought-leadership, NOT a sales pitch. At most a soft mention of the business.
- 4-8 relevant, specific "hashtags" (mix of niche + broad). Always include these
  brand hashtags if they fit: {brand_tags}
- A short "image_prompt": a vivid, brand-safe description for an illustrative image
  (no text overlays, no logos, professional, on-theme).
- A "cta_link": the single most relevant URL to include (usually the website) or null.

Return JSON exactly like:
{{
  "theme": "...",
  "hook": "...",
  "body": "...",
  "hashtags": ["#...", "..."],
  "image_prompt": "...",
  "cta_link": "https://... or null"
}}"""


def pick_theme(business: BusinessProfile, for_day: Optional[date] = None) -> str:
    """Deterministically rotate through themes so each day differs."""
    themes = business.themes_or_default()
    day = for_day or date.today()
    return themes[day.toordinal() % len(themes)]


def generate_post(
    llm: LLMClient,
    business: BusinessProfile,
    *,
    theme: Optional[str] = None,
    recent_hooks: Optional[list[str]] = None,
    strategy: Optional[StrategyContext] = None,
) -> GeneratedPost:
    theme = theme or pick_theme(business)
    recent_block = ""
    if recent_hooks:
        joined = "\n".join(f"  - {h}" for h in recent_hooks[-10:])
        recent_block = (
            "\nDo NOT repeat the angle or opening of these recent posts:\n"
            + joined
            + "\n"
        )

    strategy_block = ""
    if strategy:
        block = strategy.for_prompt()
        if block:
            strategy_block = "\nSTRATEGY & POSITIONING (follow closely):\n" + block + "\n"

    prompt = USER_PROMPT_TEMPLATE.format(
        name=business.name,
        sector=business.sector or "(unspecified)",
        vision=business.vision or "(unspecified)",
        product_info=business.product_info or "(unspecified)",
        website=business.website or "(none)",
        voice=business.brand_voice,
        language=business.language,
        theme=theme,
        brand_tags=" ".join(business.default_hashtags) or "(none)",
        strategy_block=strategy_block,
        recent_block=recent_block,
    )

    data = llm.generate_json(SYSTEM_PROMPT, prompt)

    hashtags = _normalize_hashtags(data.get("hashtags", []), business.default_hashtags)
    link = data.get("cta_link") or business.website
    if isinstance(link, str) and link.lower() in ("null", "none", ""):
        link = business.website

    return GeneratedPost(
        theme=data.get("theme", theme),
        hook=data.get("hook", "").strip(),
        body=data.get("body", "").strip(),
        hashtags=hashtags,
        link=link,
        image_prompt=data.get("image_prompt"),
    )


def _normalize_hashtags(tags: list, defaults: list[str]) -> list[str]:
    out: list[str] = []
    seen = set()
    for t in list(tags) + list(defaults):
        if not isinstance(t, str):
            continue
        t = t.strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + t.lstrip("#")
        key = t.lower()
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out[:10]
