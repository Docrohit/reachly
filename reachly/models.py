"""Core domain models shared by the standalone agent and the SaaS server.

These are plain pydantic models (not DB tables) so the agent harness has zero
dependency on the server. The server maps its DB rows into these objects before
handing them to the agent.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PlatformMode(str, Enum):
    api = "api"
    browser = "browser"
    off = "off"


class Platform(str, Enum):
    twitter = "twitter"
    linkedin = "linkedin"
    instagram = "instagram"


class BusinessProfile(BaseModel):
    """Everything the agent needs to know about the user's business to write
    as a credible thought leader."""

    name: str
    website: Optional[str] = None
    sector: Optional[str] = None
    vision: Optional[str] = None
    product_info: Optional[str] = None
    brand_voice: str = "Confident, helpful, and human. No hype."
    content_themes: list[str] = Field(default_factory=list)
    default_hashtags: list[str] = Field(default_factory=list)
    language: str = "English"

    def themes_or_default(self) -> list[str]:
        return self.content_themes or [
            "industry trends",
            "practical tips",
            "behind the scenes",
            "customer wins",
            "founder lessons",
        ]


class PlatformCredentials(BaseModel):
    """Credentials + mode for one platform. Secret fields are never logged."""

    platform: Platform
    mode: PlatformMode = PlatformMode.off

    # API-mode tokens
    api_token: Optional[str] = None          # twitter oauth2 / linkedin access / ig access
    extra: dict[str, str] = Field(default_factory=dict)  # urn, user_id, etc.

    # Browser-mode credentials
    username: Optional[str] = None
    password: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return self.mode != PlatformMode.off


class GeneratedMedia(BaseModel):
    kind: str                  # "image" | "video"
    local_path: str
    public_url: Optional[str] = None
    mime_type: str = "image/png"
    prompt: Optional[str] = None


class GeneratedPost(BaseModel):
    """A single piece of content, before it is adapted per-platform."""

    theme: str
    hook: str                   # the scroll-stopping first line
    body: str                   # full long-form body (used as base)
    hashtags: list[str] = Field(default_factory=list)
    link: Optional[str] = None
    image_prompt: Optional[str] = None
    media: Optional[GeneratedMedia] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def for_platform(self, platform: Platform) -> str:
        """Render the final text for a given platform, respecting length limits."""
        tags = " ".join(self.hashtags)
        link = self.link or ""
        if platform == Platform.twitter:
            # 280 chars. Lead with the hook, keep one or two tags + link.
            short_tags = " ".join(self.hashtags[:2])
            base = self.hook.strip()
            tail = " ".join(x for x in [link, short_tags] if x).strip()
            budget = 280 - (len(tail) + 1 if tail else 0)
            text = base[:budget].rstrip()
            return f"{text}\n{tail}".strip()
        # LinkedIn / Instagram: full body.
        parts = [self.hook.strip(), "", self.body.strip()]
        if link:
            parts += ["", link]
        if tags:
            parts += ["", tags]
        return "\n".join(parts).strip()


class PostResult(BaseModel):
    platform: Platform
    ok: bool
    permalink: Optional[str] = None
    error: Optional[str] = None
    posted_at: datetime = Field(default_factory=datetime.utcnow)
