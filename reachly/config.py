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


def _bool(value: Optional[str], default: bool = False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).lower() in ("1", "yes", "true")


def _int(value: Optional[str], default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _media_plan(value: Optional[str]) -> list[str]:
    allowed = {"image", "video"}
    return [item for item in (v.lower() for v in _split(value)) if item in allowed]


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
        self.elevenlabs_api_key = env.get("ELEVENLABS_API_KEY") or None

        # Media
        self.image_provider = (env.get("IMAGE_PROVIDER") or "none").lower()
        self.gemini_image_model = env.get("GEMINI_IMAGE_MODEL") or "gemini-2.5-flash-image"
        self.video_provider = (env.get("VIDEO_PROVIDER") or "none").lower()
        self.hygaar_base_url = env.get("HYGAAR_BASE_URL") or None
        self.hygaar_api_token = env.get("HYGAAR_API_TOKEN") or None
        self.seedance_api_key = (
            env.get("SEEDANCE_API_KEY")
            or env.get("ARK_API_KEY")
            or env.get("MODELARK_API_KEY")
            or None
        )
        self.seedance_base_url = (
            env.get("SEEDANCE_BASE_URL") or "https://ark.ap-southeast.bytepluses.com/api/v3"
        )
        self.seedance_model = env.get("SEEDANCE_MODEL") or "seedance_2_5"
        self.seedance_fallback_model = env.get("SEEDANCE_FALLBACK_MODEL") or "seedance_2_0"
        self.seedance_ratio = env.get("SEEDANCE_RATIO") or "9:16"
        self.seedance_target_duration = _int(env.get("SEEDANCE_TARGET_DURATION"), 30)
        self.seedance_clip_count = _int(env.get("SEEDANCE_CLIP_COUNT"), 0)
        self.seedance_clip_duration = _int(env.get("SEEDANCE_CLIP_DURATION"), 15)
        self.seedance_generate_audio = _bool(env.get("SEEDANCE_GENERATE_AUDIO"), True)
        self.seedance_watermark = _bool(env.get("SEEDANCE_WATERMARK"), False)
        self.longform_video_enabled = _bool(env.get("REACHLY_LONGFORM_VIDEO_ENABLED"), False)
        self.longform_video_times_raw = env.get("REACHLY_LONGFORM_VIDEO_TIMES") or ""
        self.longform_video_target_seconds = _int(env.get("REACHLY_LONGFORM_VIDEO_TARGET_SECONDS"), 90)
        self.longform_video_card_seconds = _int(env.get("REACHLY_LONGFORM_VIDEO_CARD_SECONDS"), 18)
        self.longform_video_max_card_retries = _int(env.get("REACHLY_LONGFORM_VIDEO_MAX_CARD_RETRIES"), 2)
        self.longform_video_title_alignment_threshold = _int(
            env.get("REACHLY_LONGFORM_VIDEO_TITLE_ALIGNMENT_THRESHOLD"),
            7,
        )
        self.longform_video_qc_enabled = _bool(env.get("REACHLY_LONGFORM_VIDEO_QC"), True)
        self.longform_video_qc_model = env.get("REACHLY_LONGFORM_VIDEO_QC_MODEL") or "gemini-2.5-flash"
        self.openai_transcription_model = (
            env.get("REACHLY_OPENAI_TRANSCRIPTION_MODEL") or "gpt-4o-transcribe"
        )
        self.openai_transcription_fallback_model = (
            env.get("REACHLY_OPENAI_TRANSCRIPTION_FALLBACK_MODEL") or "whisper-1"
        )
        self.video_voiceover_enabled = _bool(env.get("REACHLY_VIDEO_VOICEOVER"), True)
        self.video_voiceover_provider = (
            env.get("REACHLY_VIDEO_VOICEOVER_PROVIDER") or "elevenlabs"
        ).lower()
        self.video_voiceover_model = env.get("REACHLY_VIDEO_VOICEOVER_MODEL") or "tts-1"
        self.video_voiceover_voice = env.get("REACHLY_VIDEO_VOICEOVER_VOICE") or "alloy"
        self.elevenlabs_voice_id = (
            env.get("REACHLY_ELEVENLABS_VOICE_ID")
            or env.get("ELEVENLABS_VOICE_ID")
            or "JBFqnCBsd6RMkjVDRZzb"
        )
        self.elevenlabs_model = (
            env.get("REACHLY_ELEVENLABS_MODEL")
            or env.get("ELEVENLABS_MODEL_ID")
            or "eleven_v3"
        )
        self.elevenlabs_output_format = (
            env.get("REACHLY_ELEVENLABS_OUTPUT_FORMAT") or "mp3_44100_128"
        )
        self.spoken_brand_name = env.get("REACHLY_SPOKEN_BRAND_NAME") or (
            "Haigaar" if self.business.name.strip().lower() == "hygaar" else self.business.name
        )
        self.daily_media_plan = _media_plan(env.get("REACHLY_DAILY_MEDIA_PLAN"))
        if not self.daily_media_plan and self.video_provider != "none":
            self.daily_media_plan = ["image", "image", "image", "video", "video"]
        self.brand_logo_path = env.get("BRAND_LOGO_PATH") or None
        self.brand_logo_position = env.get("BRAND_LOGO_POSITION") or "bottom-right"

        # Behaviour
        self.attach_image = _bool(env.get("ATTACH_IMAGE"), True)
        self.dry_run = _bool(env.get("DRY_RUN"), True)
        self.timezone = env.get("TIMEZONE") or "UTC"
        self.post_time = env.get("POST_TIME") or "09:30"
        self.post_times_raw = env.get("POST_TIMES") or ""
        self.instagram_offset_minutes = env.get("INSTAGRAM_OFFSET_MINUTES") or "5"
        self.public_media_base_url = env.get("PUBLIC_MEDIA_BASE_URL") or None
        self.public_media_dir = env.get("PUBLIC_MEDIA_DIR") or None

        # Strategy context (Hygaar: point at hdb_backend on server)
        self.context_repo = env.get("REACHLY_CONTEXT_REPO") or None
        self.agents_md_path = env.get("REACHLY_AGENTS_MD") or None
        self.product_theory_path = env.get("REACHLY_PRODUCT_THEORY_MD") or None
        self.context_doc_paths = _split(env.get("REACHLY_CONTEXT_DOCS"))
        self.posting_style = env.get("REACHLY_POSTING_STYLE") or "thought_leader"
        self.dashboard_token = env.get("REACHLY_DASHBOARD_TOKEN") or None
        self.dashboard_port = int(env.get("REACHLY_DASHBOARD_PORT") or "8765")
        self.enable_engagement = _bool(env.get("REACHLY_ENABLE_ENGAGEMENT"), False)
        self.engagement_delay_minutes = _int(env.get("REACHLY_ENGAGEMENT_DELAY_MINUTES"), 30)
        self.engagement_max_comments = _int(env.get("REACHLY_ENGAGEMENT_MAX_COMMENTS"), 3)
        self.text_platform_image_rate = float(env.get("REACHLY_TEXT_PLATFORM_IMAGE_RATE") or "0.5")
        self.linkedin_image_rate = (
            float(env["REACHLY_LINKEDIN_IMAGE_RATE"])
            if env.get("REACHLY_LINKEDIN_IMAGE_RATE")
            else None
        )
        self.twitter_image_rate = (
            float(env["REACHLY_TWITTER_IMAGE_RATE"])
            if env.get("REACHLY_TWITTER_IMAGE_RATE")
            else None
        )
        self.medium_times_raw = env.get("MEDIUM_TIMES") or "09:30,14:30,19:30"
        self.medium_image_aspect_ratio = env.get("MEDIUM_IMAGE_ASPECT_RATIO") or "16:9"

        self.data_dir = Path(env.get("DATA_DIR") or "./.reachly_data").expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.platforms = self._build_platforms(env)

    def _build_platforms(self, env: dict) -> dict[Platform, PlatformCredentials]:
        out: dict[Platform, PlatformCredentials] = {}

        out[Platform.twitter] = PlatformCredentials(
            platform=Platform.twitter,
            mode=PlatformMode(env.get("TWITTER_MODE", "off")),
            api_token=env.get("TWITTER_OAUTH2_TOKEN") or None,
            extra={
                "login_identifier": env.get("TWITTER_LOGIN_IDENTIFIER", ""),
                "consumer_key": env.get("TWITTER_CONSUMER_KEY", ""),
                "consumer_secret": env.get("TWITTER_CONSUMER_SECRET", ""),
                "access_token": env.get("TWITTER_ACCESS_TOKEN", ""),
                "access_token_secret": env.get("TWITTER_ACCESS_TOKEN_SECRET", ""),
            },
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
        out[Platform.medium] = PlatformCredentials(
            platform=Platform.medium,
            mode=PlatformMode(env.get("MEDIUM_MODE", "off")),
            extra={
                "publish_status": env.get("MEDIUM_PUBLISH_STATUS", "draft"),
                "expected_account": env.get("MEDIUM_EXPECTED_ACCOUNT", ""),
            },
            username=env.get("MEDIUM_EMAIL") or None,
            password=env.get("MEDIUM_PASSWORD") or None,
        )
        out[Platform.youtube] = PlatformCredentials(
            platform=Platform.youtube,
            mode=PlatformMode(env.get("YOUTUBE_MODE", "off")),
            api_token=env.get("YOUTUBE_ACCESS_TOKEN") or None,
            extra={
                "refresh_token": env.get("YOUTUBE_REFRESH_TOKEN", ""),
                "client_id": env.get("YOUTUBE_CLIENT_ID", ""),
                "client_secret": env.get("YOUTUBE_CLIENT_SECRET", ""),
                "token_uri": env.get("YOUTUBE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
                "privacy_status": env.get("YOUTUBE_PRIVACY_STATUS", "private"),
                "category_id": env.get("YOUTUBE_CATEGORY_ID", "22"),
                "notify_subscribers": env.get("YOUTUBE_NOTIFY_SUBSCRIBERS", "false"),
                "default_tags": env.get("YOUTUBE_DEFAULT_TAGS", ""),
            },
        )
        return out

    @classmethod
    def from_env_file(cls, path: str | os.PathLike = ".env") -> "AgentConfig":
        load_dotenv(path, override=False)
        return cls()
