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
{performance_block}
{recent_block}
Requirements:
- A scroll-stopping one-line "hook".
- A "body" of 90-160 words: valuable, specific, story- or insight-driven.
  Thought-leadership, NOT a sales pitch. At most a soft mention of the business.
- 4-8 relevant, specific "hashtags" (mix of niche + broad). Always include these
  brand hashtags if they fit: {brand_tags}
- A short "image_prompt": a vivid, brand-safe description for a concrete ecommerce
  product/fashion image. It must show real products or models/styling scenes that
  fit the business category. Avoid abstract tech graphics, circuit boards, charts,
  dashboards, metaphors, floating icons, text overlays, fake/generated logos, and
  generic stock imagery. Leave natural negative space in one corner for the provided
  brand logo to be placed later. For Hygaar-like businesses, prefer western dresses,
  ethnic wear, sarees, kurtas, jewellery, beauty, home decor, accessories, fabric
  texture, drape, fit, styling, PDP/catalog needs, or behind-the-scenes product shoot
  setups.
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

ARTICLE_SYSTEM_PROMPT = """You are a senior B2B editorial strategist writing for
CEOs, CMOs, ecommerce leaders, marketing heads, catalogue heads, and founders
researching AI product photography. You write sharp Medium articles that earn
attention with a strong commercial insight, explain the operational problem
clearly, and naturally improve search discoverability for Hygaar. You sound like
a serious CTO/operator, not an ad writer. Avoid fluff, fake statistics, and
generic AI hype. Output ONLY valid JSON, no markdown fences."""

ARTICLE_PROMPT_TEMPLATE = """Write ONE original Medium article for today.

BUSINESS:
- Name: {name}
- Sector: {sector}
- Vision: {vision}
- Product/Service: {product_info}
- Website: {website}
- Brand voice: {voice}
- Language: {language}

TODAY'S THEME: {theme}
{strategy_block}
{performance_block}
{recent_block}
Audience:
- CEOs
- CMOs and marketing heads
- Ecommerce/catalogue heads
- Brand and creative operations leaders
- Founders and operators searching for AI photoshoots, AI product photography,
  catalogue photography with AI, ecommerce AI shoots, or bulk SKU image generation

Requirements:
- "title": attention-capturing and commercially serious, not clickbait.
- "title" or "subtitle" should naturally include one search-intent phrase such
  as AI product photography, AI photoshoot, ecommerce AI shoot, catalogue
  photography, product photography with AI, or bulk SKU image generation.
- "subtitle": one concise line that makes the article relevant to leaders.
- "body": 850-1300 words, written in short readable paragraphs for Medium.
  It should create urgency around product media, catalogue consistency, SKU
  operations, launch speed, brand trust, and marketing execution. Include
  practical language a buyer would search for: AI photoshoots for products,
  AI product photography, product and catalogue photography with AI, ecommerce
  AI shoots, PDP image generation, marketplace-ready product images, and bulk
  generation of SKU images, and bulk generation of SKU images. Work these phrases in naturally; do not keyword
  stuff. Mention {name} as the company building this workflow, and write from a
  CTO/operator point of view when natural.
- Include one concrete section or paragraph on how a brand should evaluate AI
  product photography tools for consistency, detail retention, workflow speed,
  review control, and catalogue scale.
- "tags": 3-5 Medium tags, no # prefix.
  Prefer tags from this pool when relevant: AI Product Photography, Ecommerce,
  Product Photography, Catalogue Management, Marketing, Retail Tech, Generative AI.
- "image_prompt": one 16:9 editorial ecommerce image prompt. It must be concrete,
  premium, brand-safe, and relevant to product catalogues, fashion/beauty/home
  products, marketing operations, or ecommerce teams. No text overlays, fake UI,
  fake logos, abstract charts, or generic stock office scenes.
- "cta_link": the single most relevant URL to include or null.

Return JSON exactly like:
{{
  "theme": "...",
  "title": "...",
  "subtitle": "...",
  "body": "...",
  "tags": ["...", "..."],
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
    performance_context: Optional[str] = None,
    newness_context: Optional[str] = None,
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
    if newness_context:
        recent_block += (
            "\nLAST 3 POSTS BY PLATFORM (create a clearly different angle, example, "
            "format, and opening from these):\n"
            + newness_context.strip()
            + "\n"
        )

    strategy_block = ""
    if strategy:
        block = strategy.for_prompt()
        if block:
            strategy_block = "\nSTRATEGY & POSITIONING (follow closely):\n" + block + "\n"

    performance_block = ""
    if performance_context:
        performance_block = (
            "\nRECENT PERFORMANCE / ANALYTICS CONTEXT:\n"
            + performance_context.strip()
            + "\nUse this to improve today's idea: keep what earned engagement, "
            "avoid what looked repetitive or weak, and choose one fresh insight.\n"
        )

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
        performance_block=performance_block,
        recent_block=recent_block,
    )

    data = llm.generate_json(SYSTEM_PROMPT, prompt)

    hashtags = _normalize_hashtags(data.get("hashtags", []), business.default_hashtags)
    link = data.get("cta_link") or business.website
    if isinstance(link, str) and link.lower() in ("null", "none", ""):
        link = business.website

    image_prompt = _product_image_prompt(data.get("image_prompt"), business)

    return GeneratedPost(
        theme=data.get("theme", theme),
        hook=data.get("hook", "").strip(),
        body=data.get("body", "").strip(),
        hashtags=hashtags,
        link=link,
        image_prompt=image_prompt,
    )


def generate_medium_article(
    llm: LLMClient,
    business: BusinessProfile,
    *,
    theme: Optional[str] = None,
    recent_hooks: Optional[list[str]] = None,
    performance_context: Optional[str] = None,
    newness_context: Optional[str] = None,
    strategy: Optional[StrategyContext] = None,
) -> GeneratedPost:
    theme = theme or pick_theme(business)
    recent_block = ""
    if recent_hooks:
        joined = "\n".join(f"  - {h}" for h in recent_hooks[-10:])
        recent_block = "\nDo NOT repeat these recent article/post openings:\n" + joined + "\n"
    if newness_context:
        recent_block += (
            "\nRECENT POSTS TO DIFFERENTIATE FROM:\n"
            + newness_context.strip()
            + "\n"
        )

    strategy_block = ""
    if strategy:
        block = strategy.for_prompt()
        if block:
            strategy_block = "\nSTRATEGY & POSITIONING (follow closely):\n" + block + "\n"

    performance_block = ""
    if performance_context:
        performance_block = (
            "\nRECENT PERFORMANCE / ANALYTICS CONTEXT:\n"
            + performance_context.strip()
            + "\nUse this to choose a fresh, stronger article angle.\n"
        )

    prompt = ARTICLE_PROMPT_TEMPLATE.format(
        name=business.name,
        sector=business.sector or "(unspecified)",
        vision=business.vision or "(unspecified)",
        product_info=business.product_info or "(unspecified)",
        website=business.website or "(none)",
        voice=business.brand_voice,
        language=business.language,
        theme=theme,
        strategy_block=strategy_block,
        performance_block=performance_block,
        recent_block=recent_block,
    )

    data = llm.generate_json(ARTICLE_SYSTEM_PROMPT, prompt)
    tags = _normalize_medium_tags(data.get("tags", []))
    subtitle = str(data.get("subtitle") or "").strip()
    body = str(data.get("body") or "").strip()
    if subtitle and not body.startswith(subtitle):
        body = f"{subtitle}\n\n{body}"
    link = data.get("cta_link") or business.website
    if isinstance(link, str) and link.lower() in ("null", "none", ""):
        link = business.website
    image_prompt = _medium_image_prompt(data.get("image_prompt"), business)

    return GeneratedPost(
        theme=data.get("theme", theme),
        hook=str(data.get("title") or "").strip(),
        body=body,
        hashtags=tags,
        link=link,
        image_prompt=image_prompt,
    )


def generate_engagement_comment(
    llm: LLMClient,
    business: BusinessProfile,
    *,
    hashtag: str,
    source_post_text: str,
) -> str:
    prompt = f"""Write one genuine LinkedIn comment for a post found under {hashtag}.

Business context:
- Name: {business.name}
- Sector: {business.sector or "(unspecified)"}
- Voice: {business.brand_voice}

Post to respond to:
{source_post_text[:1800]}

Rules:
- 1-2 sentences, under 220 characters.
- Sound like a real operator adding value, not a bot.
- Mention one specific idea from the post.
- No pitch, no link, no hashtags, no emojis.
- Do not say "great post" unless you add a specific reason.

Return only the comment text."""
    text = llm.generate(SYSTEM_PROMPT, prompt).strip()
    return " ".join(text.split())[:260]


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


def _normalize_medium_tags(tags: list) -> list[str]:
    out: list[str] = []
    seen = set()
    for tag in tags:
        if not isinstance(tag, str):
            continue
        clean = tag.strip().lstrip("#")
        if not clean:
            continue
        key = clean.lower()
        if key not in seen:
            seen.add(key)
            out.append(clean[:25])
    return out[:5]


def _product_image_prompt(prompt: object, business: BusinessProfile) -> str:
    raw = prompt.strip() if isinstance(prompt, str) else ""
    if not raw:
        raw = (
            "A premium ecommerce product photo featuring styled apparel, accessories, "
            "or home/beauty products in a realistic campaign setup."
        )
    context = " ".join(
        part
        for part in [
            business.sector or "",
            business.product_info or "",
            " ".join(business.content_themes),
        ]
        if part
    )
    return (
        f"{raw}\n\n"
        "Hard image requirements: create a concrete, realistic ecommerce/fashion "
        "visual with actual products, garments, models, styling details, fabric "
        "texture, or catalog/PDP context. Do not create abstract circuit boards, "
        "tech diagrams, dashboards, charts, floating icons, text overlays, fake logos, "
        "or metaphor-only visuals. Leave subtle clean space in a corner for the real "
        "brand logo to be added after generation. Avoid overusing sneakers; rotate through western "
        "dresses, ethnic wear, sarees, kurtas, jewellery, beauty, home decor, bags, "
        f"watches, and accessories where relevant. Business context: {context[:900]}"
    )


def _medium_image_prompt(prompt: object, business: BusinessProfile) -> str:
    raw = prompt.strip() if isinstance(prompt, str) else ""
    if not raw:
        raw = (
            "A premium 16:9 editorial ecommerce visual showing a polished product "
            "catalogue production setup with fashion, beauty, or home products."
        )
    context = " ".join(
        part
        for part in [
            business.sector or "",
            business.product_info or "",
            " ".join(business.content_themes),
        ]
        if part
    )
    return (
        f"{raw}\n\n"
        "Hard image requirements: 16:9 horizontal editorial image, realistic premium "
        "ecommerce/product media scene, no text overlays, no fake dashboards, no fake "
        "logos, no abstract charts, no generic office stock photo. Show tangible "
        "products, styling, catalogue production, campaign visuals, or quality-control "
        f"context. Business context: {context[:900]}"
    )
