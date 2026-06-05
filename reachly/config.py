"""Configuration for the standalone (self-hosted) agent.

Loads everything from environment variables / a local `.env` file and assembles
the strongly-typed objects the agent harness consumes. The SaaS server does NOT
use this module — it builds the same objects from the database instead.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .models import (
    BusinessProfile,
    Platform,
    PlatformCredentials,
    PlatformMode,
)


def _split(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _hashtags(value: Optional[str]) -> list[str]:
    out: list[str] = []
    for raw in (value or "").replace(",", " ").split():
        raw = raw.strip()
        if not raw:
            continue
        out.append(raw if raw.startswith("#") else f"#{raw}")
    return out


class AgentConfig:
    """Resolved configuration object for one agent run."""

    def __init__(self, env: Optional[dict] = None):
        env = env or os.environ

        self.business = BusinessProfile(
            name=env.get("BUSINESS_NAME", "My Business"),
            website=env.get("BUSINESS_WEBSITE") or None,
            sector=env.get("BUSINESS_SECTOR") or None,
            vision=env.get("BUSINESS_VISION") or None,
            product_info=env.get("BUSINESS_PRODUCT_INFO") or None,
            brand_voice=env.get("BRAND_VOICE") or "Confident, helpful, and human. No hype.",
            content_themes=_split(env.get("CONTENT_THEMES")),
            default_hashtags=_hashtags(env.get("DEFAULT_HASHTAGS")),
            language=env.get("POST_LANGUAGE") or "English",
        )

        # LLM
        self.llm_provider = (env.get("LLM_PROVIDER") or "gemini").lower()
        self.llm_model = env.get("LLM_MODEL") or None
        self.gemini_api_key = env.get("GEMINI_API_KEY") or None
        self.openai_api_key = env.get("OPENAI_API_KEY") or None
        self.anthropic_api_key = env.get("ANTHROPIC_API_KEY") or None

        # Media
        self.image_provider = (env.get("IMAGE_PROVIDER") or "none").lower()
        self.gemini_image_model = env.get("GEMINI_IMAGE_MODEL") or "gemini-2.5-flash-image"
        self.video_provider = (env.get("VIDEO_PROVIDER") or "none").lower()
        self.hygaar_base_url = env.get("HYGAAR_BASE_URL") or None
        self.hygaar_api_token = env.get("HYGAAR_API_TOKEN") or None

        # Behaviour
        self.attach_image = (env.get("ATTACH_IMAGE") or "yes").lower() in ("1", "yes", "true")
        self.dry_run = (env.get("DRY_RUN") or "yes").lower() in ("1", "yes", "true")
        self.timezone = env.get("TIMEZONE") or "UTC"
        self.post_time = env.get("POST_TIME") or "09:30"
        self.post_times_raw = env.get("POST_TIMES") or ""
        self.instagram_offset_minutes = env.get("INSTAGRAM_OFFSET_MINUTES") or "5"
        self.public_media_base_url = env.get("PUBLIC_MEDIA_BASE_URL") or None

        # Strategy context (Hygaar: point at hdb_backend on server)
        self.context_repo = env.get("REACHLY_CONTEXT_REPO") or None
        self.agents_md_path = env.get("REACHLY_AGENTS_MD") or None
        self.product_theory_path = env.get("REACHLY_PRODUCT_THEORY_MD") or None
        self.posting_style = env.get("REACHLY_POSTING_STYLE") or "thought_leader"
        self.dashboard_token = env.get("REACHLY_DASHBOARD_TOKEN") or None
        self.dashboard_port = int(env.get("REACHLY_DASHBOARD_PORT") or "8765")
        self.enable_engagement = (
            env.get("REACHLY_ENABLE_ENGAGEMENT") or "no"
        ).lower() in ("1", "yes", "true")
        self.engagement_delay_minutes = int(env.get("REACHLY_ENGAGEMENT_DELAY_MINUTES") or "30")
        self.engagement_max_comments = int(env.get("REACHLY_ENGAGEMENT_MAX_COMMENTS") or "3")

        self.data_dir = Path(env.get("DATA_DIR") or "./.reachly_data").expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.platforms = self._build_platforms(env)

    def _build_platforms(self, env: dict) -> dict[Platform, PlatformCredentials]:
        out: dict[Platform, PlatformCredentials] = {}

        out[Platform.twitter] = PlatformCredentials(
            platform=Platform.twitter,
            mode=PlatformMode(env.get("TWITTER_MODE", "off")),
            api_token=env.get("TWITTER_OAUTH2_TOKEN") or None,
            extra={"login_identifier": env.get("TWITTER_LOGIN_IDENTIFIER", "")},
            username=env.get("TWITTER_USERNAME") or None,
            password=env.get("TWITTER_PASSWORD") or None,
        )

        out[Platform.linkedin] = PlatformCredentials(
            platform=Platform.linkedin,
            mode=PlatformMode(env.get("LINKEDIN_MODE", "off")),
            api_token=env.get("LINKEDIN_ACCESS_TOKEN") or None,
            extra={
                "person_urn": env.get("LINKEDIN_PERSON_URN", ""),
                # Browser mode: post as this Company Page (exact name) instead of
                # your personal profile. Leave blank to post as yourself.
                "post_as": env.get("LINKEDIN_POST_AS", ""),
                # Browser mode: open the company admin URL directly and create
                # from that surface. Preferred over the generic feed composer.
                "company_admin_url": env.get("LINKEDIN_COMPANY_ADMIN_URL", ""),
                # API mode: organization id to post as a Page (uses w_organization_social).
                "organization_id": env.get("LINKEDIN_ORGANIZATION_ID", ""),
            },
            username=env.get("LINKEDIN_EMAIL") or None,
            password=env.get("LINKEDIN_PASSWORD") or None,
        )

        out[Platform.instagram] = PlatformCredentials(
            platform=Platform.instagram,
            mode=PlatformMode(env.get("INSTAGRAM_MODE", "off")),
            api_token=env.get("INSTAGRAM_ACCESS_TOKEN") or None,
            extra={"user_id": env.get("INSTAGRAM_USER_ID", "")},
            username=env.get("INSTAGRAM_USERNAME") or None,
            password=env.get("INSTAGRAM_PASSWORD") or None,
        )
        return out

    @classmethod
    def from_env_file(cls, path: str | os.PathLike = ".env") -> "AgentConfig":
        load_dotenv(path, override=False)
        return cls()
