"""Per-user orchestration for the hosted product.

Maps DB rows -> the agent's domain objects, runs the agent, and records results.
A background scheduler checks every minute for users whose local posting time has
arrived.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlmodel import select

from reachly.agent import Agent, AgentSettings
from reachly.knowledge_bank import knowledge_bank_path
from reachly.longform_video import LongFormManualBrief
from reachly.models import (
    BusinessProfile,
    Platform,
    PlatformCredentials,
    PlatformMode,
)
from reachly.settings_store import instagram_times_for

from .crypto import decrypt_dict
from .db import BusinessProfileRow, PlatformCredRow, PostLogRow, User, get_session
from .settings import get_settings

logger = logging.getLogger("reachly.orchestrator")


def build_agent_for_user(user: User) -> Agent | None:
    settings = get_settings()
    use_server_env = _server_env_fallback_allowed(user, settings)
    with get_session() as session:
        profile_row = session.exec(
            select(BusinessProfileRow).where(BusinessProfileRow.user_id == user.id)
        ).first()
        if not profile_row:
            logger.info("User %s has no business profile yet; skipping.", user.id)
            return None
        cred_rows = session.exec(
            select(PlatformCredRow).where(PlatformCredRow.user_id == user.id)
        ).all()

    providers = decrypt_dict(profile_row.providers_vault) if profile_row.providers_vault else {}
    media_plan = _media_plan(
        _provider_value(
            providers,
            "daily_media_plan",
            "REACHLY_DAILY_MEDIA_PLAN",
            use_env=use_server_env,
        )
    )
    video_provider = _provider_value(
        providers,
        "video_provider",
        "VIDEO_PROVIDER",
        default=profile_row.video_provider,
        use_env=use_server_env,
    )
    if not media_plan and video_provider != "none":
        media_plan = ["image", "image", "image", "longform_video", "short_video", "image"]

    business = BusinessProfile(
        name=profile_row.name,
        website=profile_row.website,
        sector=profile_row.sector,
        vision=profile_row.vision,
        product_info=profile_row.product_info,
        brand_voice=profile_row.brand_voice,
        content_themes=[t.strip() for t in (profile_row.content_themes or "").split(",") if t.strip()],
        default_hashtags=_normalize_tags(profile_row.default_hashtags),
        language=profile_row.language,
    )

    platforms: dict[Platform, PlatformCredentials] = {}
    for row in cred_rows:
        secrets = decrypt_dict(row.vault) if row.vault else {}
        platform = Platform(row.platform)
        platforms[platform] = _creds_from_secrets(
            platform,
            PlatformMode(row.mode),
            secrets,
            use_env=use_server_env,
        )
    if use_server_env:
        for platform in Platform:
            if platform in platforms:
                continue
            creds = _creds_from_secrets(platform, PlatformMode.off, {}, use_env=True)
            if creds.enabled:
                platforms[platform] = creds

    data_dir = Path(settings.media_dir).parent / "agents" / f"user_{user.id}"
    global_knowledge_bank = knowledge_bank_path(Path(settings.media_dir).parent / "knowledge")
    context_doc_paths = [str(global_knowledge_bank)] if global_knowledge_bank.is_file() else []
    agent_settings = AgentSettings(
        llm_provider=_provider_value(
            providers,
            "llm_provider",
            "LLM_PROVIDER",
            default=profile_row.llm_provider,
            use_env=use_server_env,
        ),
        llm_model=_provider_value(providers, "llm_model", "LLM_MODEL", use_env=use_server_env),
        gemini_api_key=_provider_value(
            providers,
            "gemini_api_key",
            "GEMINI_API_KEY",
            use_env=use_server_env,
        ),
        openai_api_key=_provider_value(
            providers,
            "openai_api_key",
            "OPENAI_API_KEY",
            use_env=use_server_env,
        ),
        anthropic_api_key=_provider_value(
            providers,
            "anthropic_api_key",
            "ANTHROPIC_API_KEY",
            use_env=use_server_env,
        ),
        image_provider=_provider_value(
            providers,
            "image_provider",
            "IMAGE_PROVIDER",
            default=profile_row.image_provider,
            use_env=use_server_env,
        ),
        gemini_image_model=_provider_value(
            providers,
            "gemini_image_model",
            "GEMINI_IMAGE_MODEL",
            default="gemini-2.5-flash-image",
            use_env=use_server_env,
        ),
        video_provider=video_provider,
        hygaar_base_url=_provider_value(
            providers,
            "hygaar_base_url",
            "HYGAAR_BASE_URL",
            use_env=use_server_env,
        ),
        hygaar_api_token=_provider_value(
            providers,
            "hygaar_api_token",
            "HYGAAR_API_TOKEN",
            use_env=use_server_env,
        ),
        seedance_api_key=_provider_value(
            providers,
            "seedance_api_key",
            "SEEDANCE_API_KEY",
            "ARK_API_KEY",
            "MODELARK_API_KEY",
            use_env=use_server_env,
        ),
        seedance_base_url=_provider_value(
            providers,
            "seedance_base_url",
            "SEEDANCE_BASE_URL",
            default="https://ark.ap-southeast.bytepluses.com/api/v3",
            use_env=use_server_env,
        ),
        seedance_model=_provider_value(
            providers,
            "seedance_model",
            "SEEDANCE_MODEL",
            default="seedance_2_5",
            use_env=use_server_env,
        ),
        seedance_fallback_model=_provider_value(
            providers,
            "seedance_fallback_model",
            "SEEDANCE_FALLBACK_MODEL",
            default="seedance_2_0",
            use_env=use_server_env,
        ),
        seedance_ratio=_provider_value(
            providers,
            "seedance_ratio",
            "SEEDANCE_RATIO",
            default="9:16",
            use_env=use_server_env,
        ),
        seedance_target_duration=_as_int(
            _provider_value(
                providers,
                "seedance_target_duration",
                "SEEDANCE_TARGET_DURATION",
                use_env=use_server_env,
            ),
            30,
        ),
        seedance_clip_count=_as_int(
            _provider_value(
                providers,
                "seedance_clip_count",
                "SEEDANCE_CLIP_COUNT",
                use_env=use_server_env,
            ),
            0,
        ),
        seedance_clip_duration=_as_int(
            _provider_value(
                providers,
                "seedance_clip_duration",
                "SEEDANCE_CLIP_DURATION",
                use_env=use_server_env,
            ),
            15,
        ),
        seedance_generate_audio=_as_bool(
            _provider_value(
                providers,
                "seedance_generate_audio",
                "SEEDANCE_GENERATE_AUDIO",
                use_env=use_server_env,
            ),
            True,
        ),
        seedance_watermark=_as_bool(
            _provider_value(
                providers,
                "seedance_watermark",
                "SEEDANCE_WATERMARK",
                use_env=use_server_env,
            ),
            False,
        ),
        longform_video_enabled=user.longform_video_enabled,
        longform_video_target_seconds=_as_int(
            _provider_value(
                providers,
                "longform_video_target_seconds",
                "REACHLY_LONGFORM_VIDEO_TARGET_SECONDS",
                use_env=use_server_env,
            ),
            90,
        ),
        longform_video_card_seconds=_as_int(
            _provider_value(
                providers,
                "longform_video_card_seconds",
                "REACHLY_LONGFORM_VIDEO_CARD_SECONDS",
                use_env=use_server_env,
            ),
            18,
        ),
        longform_video_max_card_retries=_as_int(
            _provider_value(
                providers,
                "longform_video_max_card_retries",
                "REACHLY_LONGFORM_VIDEO_MAX_CARD_RETRIES",
                use_env=use_server_env,
            ),
            2,
        ),
        longform_video_title_alignment_threshold=_as_int(
            _provider_value(
                providers,
                "longform_video_title_alignment_threshold",
                "REACHLY_LONGFORM_VIDEO_TITLE_ALIGNMENT_THRESHOLD",
                use_env=use_server_env,
            ),
            7,
        ),
        longform_video_qc_enabled=_as_bool(
            _provider_value(
                providers,
                "longform_video_qc_enabled",
                "REACHLY_LONGFORM_VIDEO_QC",
                use_env=use_server_env,
            ),
            True,
        ),
        longform_video_qc_model=_provider_value(
            providers,
            "longform_video_qc_model",
            "REACHLY_LONGFORM_VIDEO_QC_MODEL",
            default="gemini-2.5-flash",
            use_env=use_server_env,
        ),
        openai_transcription_model=_provider_value(
            providers,
            "openai_transcription_model",
            "REACHLY_OPENAI_TRANSCRIPTION_MODEL",
            default="gpt-4o-transcribe",
            use_env=use_server_env,
        ),
        openai_transcription_fallback_model=_provider_value(
            providers,
            "openai_transcription_fallback_model",
            "REACHLY_OPENAI_TRANSCRIPTION_FALLBACK_MODEL",
            default="whisper-1",
            use_env=use_server_env,
        ),
        elevenlabs_api_key=_provider_value(
            providers,
            "elevenlabs_api_key",
            "ELEVENLABS_API_KEY",
            use_env=use_server_env,
        ),
        elevenlabs_voice_id=_provider_value(
            providers,
            "elevenlabs_voice_id",
            "REACHLY_ELEVENLABS_VOICE_ID",
            "ELEVENLABS_VOICE_ID",
            default="JBFqnCBsd6RMkjVDRZzb",
            use_env=use_server_env,
        ),
        elevenlabs_model=_provider_value(
            providers,
            "elevenlabs_model",
            "REACHLY_ELEVENLABS_MODEL",
            "ELEVENLABS_MODEL_ID",
            default="eleven_v3",
            use_env=use_server_env,
        ),
        elevenlabs_output_format=_provider_value(
            providers,
            "elevenlabs_output_format",
            "REACHLY_ELEVENLABS_OUTPUT_FORMAT",
            default="mp3_44100_128",
            use_env=use_server_env,
        ),
        spoken_brand_name=_provider_value(
            providers,
            "spoken_brand_name",
            "REACHLY_SPOKEN_BRAND_NAME",
            use_env=use_server_env,
        ),
        daily_media_plan=media_plan,
        brand_logo_path=_provider_value(
            providers,
            "brand_logo_path",
            "BRAND_LOGO_PATH",
            use_env=use_server_env,
        ),
        brand_logo_position=_provider_value(
            providers,
            "brand_logo_position",
            "BRAND_LOGO_POSITION",
            default="bottom-right",
            use_env=use_server_env,
        ),
        attach_image=user.attach_image,
        dry_run=user.dry_run,
        data_dir=data_dir,
        public_media_base_url=settings.public_media_url,
        public_media_dir=Path(settings.media_dir),
        context_repo=_provider_value(
            providers,
            "context_repo",
            "REACHLY_CONTEXT_REPO",
            default=profile_row.context_repo,
            use_env=use_server_env,
        ),
        context_doc_paths=context_doc_paths,
        posting_style=_provider_value(
            providers,
            "posting_style",
            "REACHLY_POSTING_STYLE",
            default=profile_row.posting_style,
            use_env=use_server_env,
        ),
        enable_engagement=user.enable_engagement,
        engagement_delay_minutes=user.engagement_delay_minutes,
        engagement_max_comments=user.engagement_max_comments,
        text_platform_image_rate=float(
            _provider_value(
                providers,
                "text_platform_image_rate",
                "REACHLY_TEXT_PLATFORM_IMAGE_RATE",
                default="0.5",
                use_env=use_server_env,
            )
        ),
        linkedin_image_rate=(
            float(providers["linkedin_image_rate"])
            if providers.get("linkedin_image_rate")
            else float(os.environ["REACHLY_LINKEDIN_IMAGE_RATE"])
            if use_server_env and os.getenv("REACHLY_LINKEDIN_IMAGE_RATE")
            else None
        ),
        twitter_image_rate=(
            float(providers["twitter_image_rate"])
            if providers.get("twitter_image_rate")
            else float(os.environ["REACHLY_TWITTER_IMAGE_RATE"])
            if use_server_env and os.getenv("REACHLY_TWITTER_IMAGE_RATE")
            else None
        ),
    )
    if profile_row.goals.strip():
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "goals.md").write_text(profile_row.goals, encoding="utf-8")
    return Agent(business, platforms, agent_settings)


def _normalize_tags(value: str) -> list[str]:
    out = []
    for raw in (value or "").replace(",", " ").split():
        raw = raw.strip()
        if raw:
            out.append(raw if raw.startswith("#") else f"#{raw}")
    return out


def _server_env_fallback_allowed(user: User, settings) -> bool:
    roles = {role.strip().lower() for role in (user.roles or "").split(",") if role.strip()}
    email = (user.email or "").strip().lower()
    return user.auth_provider == "hygaar" and (
        email in settings.hygaar_pro_emails or "superadmin" in roles
    )


def _provider_value(
    source: dict,
    key: str,
    *env_names: str,
    default: str | None = None,
    use_env: bool = False,
) -> str | None:
    value = source.get(key)
    if value not in (None, ""):
        return value
    if use_env:
        for env_name in env_names:
            env_value = os.getenv(env_name)
            if env_value not in (None, ""):
                return env_value
    return default


def _platform_mode_with_env(
    platform: Platform,
    mode: PlatformMode,
    *,
    use_env: bool = False,
) -> PlatformMode:
    if not use_env:
        return mode
    env_value = os.getenv(f"{platform.value.upper()}_MODE")
    if not env_value:
        return mode
    try:
        return PlatformMode(env_value.lower())
    except ValueError:
        return mode


def _creds_from_secrets(
    platform: Platform,
    mode: PlatformMode,
    s: dict,
    *,
    use_env: bool = False,
) -> PlatformCredentials:
    mode = _platform_mode_with_env(platform, mode, use_env=use_env)
    if platform == Platform.twitter:
        return PlatformCredentials(
            platform=platform,
            mode=mode,
            api_token=_provider_value(s, "oauth2_token", "TWITTER_OAUTH2_TOKEN", use_env=use_env),
            extra={
                "login_identifier": _provider_value(
                    s,
                    "login_identifier",
                    "TWITTER_LOGIN_IDENTIFIER",
                    default="",
                    use_env=use_env,
                ),
                "consumer_key": _provider_value(
                    s,
                    "consumer_key",
                    "TWITTER_CONSUMER_KEY",
                    default="",
                    use_env=use_env,
                ),
                "consumer_secret": _provider_value(
                    s,
                    "consumer_secret",
                    "TWITTER_CONSUMER_SECRET",
                    default="",
                    use_env=use_env,
                ),
                "access_token": _provider_value(
                    s,
                    "access_token",
                    "TWITTER_ACCESS_TOKEN",
                    default="",
                    use_env=use_env,
                ),
                "access_token_secret": _provider_value(
                    s,
                    "access_token_secret",
                    "TWITTER_ACCESS_TOKEN_SECRET",
                    default="",
                    use_env=use_env,
                ),
            },
            username=_provider_value(s, "username", "TWITTER_USERNAME", use_env=use_env),
            password=_provider_value(s, "password", "TWITTER_PASSWORD", use_env=use_env),
        )
    if platform == Platform.linkedin:
        return PlatformCredentials(
            platform=platform,
            mode=mode,
            api_token=_provider_value(s, "access_token", "LINKEDIN_ACCESS_TOKEN", use_env=use_env),
            extra={
                "person_urn": _provider_value(
                    s,
                    "person_urn",
                    "LINKEDIN_PERSON_URN",
                    default="",
                    use_env=use_env,
                ),
                "organization_id": _provider_value(
                    s,
                    "organization_id",
                    "LINKEDIN_ORGANIZATION_ID",
                    default="",
                    use_env=use_env,
                ),
                "post_as": _provider_value(
                    s,
                    "post_as",
                    "LINKEDIN_POST_AS",
                    default="",
                    use_env=use_env,
                ),
                "company_admin_url": _provider_value(
                    s,
                    "company_admin_url",
                    "LINKEDIN_COMPANY_ADMIN_URL",
                    default="",
                    use_env=use_env,
                ),
            },
            username=_provider_value(s, "email", "LINKEDIN_EMAIL", use_env=use_env),
            password=_provider_value(s, "password", "LINKEDIN_PASSWORD", use_env=use_env),
        )
    if platform == Platform.instagram:
        return PlatformCredentials(
            platform=platform,
            mode=mode,
            api_token=_provider_value(s, "access_token", "INSTAGRAM_ACCESS_TOKEN", use_env=use_env),
            extra={
                "user_id": _provider_value(
                    s,
                    "user_id",
                    "INSTAGRAM_USER_ID",
                    default="",
                    use_env=use_env,
                )
            },
            username=_provider_value(s, "username", "INSTAGRAM_USERNAME", use_env=use_env),
            password=_provider_value(s, "password", "INSTAGRAM_PASSWORD", use_env=use_env),
        )
    if platform == Platform.medium:
        return PlatformCredentials(
            platform=platform,
            mode=mode,
            extra={
                "publish_status": _provider_value(
                    s,
                    "publish_status",
                    "MEDIUM_PUBLISH_STATUS",
                    default="draft",
                    use_env=use_env,
                ),
                "expected_account": _provider_value(
                    s,
                    "expected_account",
                    "MEDIUM_EXPECTED_ACCOUNT",
                    default="",
                    use_env=use_env,
                ),
            },
            username=_provider_value(s, "email", "MEDIUM_EMAIL", use_env=use_env),
            password=_provider_value(s, "password", "MEDIUM_PASSWORD", use_env=use_env),
        )
    if platform == Platform.youtube:
        return PlatformCredentials(
            platform=platform,
            mode=mode,
            api_token=_provider_value(s, "access_token", "YOUTUBE_ACCESS_TOKEN", use_env=use_env),
            extra={
                "refresh_token": _provider_value(
                    s,
                    "refresh_token",
                    "YOUTUBE_REFRESH_TOKEN",
                    default="",
                    use_env=use_env,
                ),
                "client_id": _provider_value(
                    s,
                    "client_id",
                    "YOUTUBE_CLIENT_ID",
                    default="",
                    use_env=use_env,
                ),
                "client_secret": _provider_value(
                    s,
                    "client_secret",
                    "YOUTUBE_CLIENT_SECRET",
                    default="",
                    use_env=use_env,
                ),
                "token_uri": _provider_value(
                    s,
                    "token_uri",
                    "YOUTUBE_TOKEN_URI",
                    default="https://oauth2.googleapis.com/token",
                    use_env=use_env,
                ),
                "privacy_status": _provider_value(
                    s,
                    "privacy_status",
                    "YOUTUBE_PRIVACY_STATUS",
                    default="private",
                    use_env=use_env,
                ),
                "category_id": _provider_value(
                    s,
                    "category_id",
                    "YOUTUBE_CATEGORY_ID",
                    default="22",
                    use_env=use_env,
                ),
                "notify_subscribers": _provider_value(
                    s,
                    "notify_subscribers",
                    "YOUTUBE_NOTIFY_SUBSCRIBERS",
                    default="false",
                    use_env=use_env,
                ),
                "default_tags": _provider_value(
                    s,
                    "default_tags",
                    "YOUTUBE_DEFAULT_TAGS",
                    default="",
                    use_env=use_env,
                ),
            },
        )
    raise ValueError(platform)


def run_user_now(user_id: int, theme: str | None = None) -> dict:
    with get_session() as session:
        user = session.get(User, user_id)
    if not user:
        return {"error": "user not found"}
    if not user.is_active:
        return {"error": "account not active (payment required)"}

    agent = build_agent_for_user(user)
    if not agent:
        return {"error": "no business profile configured"}

    results = agent.run_once(theme=theme)
    if user.enable_engagement and results.get(Platform.linkedin) and results[Platform.linkedin].ok:
        delay = max(1, user.engagement_delay_minutes) * 60
        threading.Timer(delay, _run_user_engagement, args=(user_id,)).start()
        logger.info("Scheduled hosted LinkedIn engagement for user %s in %ss.", user_id, delay)
    agent.close()

    _record_results(user_id, results)
    return {p.value: {"ok": r.ok, "permalink": r.permalink, "error": r.error} for p, r in results.items()}


def run_user_linkedin_slot(user_id: int, *, slot_index: int | None = None) -> dict:
    return _run_user_slot(user_id, "linkedin", slot_index=slot_index)


def run_user_instagram_slot(user_id: int) -> dict:
    return _run_user_slot(user_id, "instagram")


def run_user_medium_slot(user_id: int) -> dict:
    return _run_user_slot(user_id, "medium")


def run_user_longform_video_slot(
    user_id: int,
    *,
    theme: str | None = None,
    title: str | None = None,
    hook: str | None = None,
    payoff: str | None = None,
    publish: bool = True,
) -> dict:
    return _run_user_slot(
        user_id,
        "longform_video",
        theme=theme,
        title=title,
        hook=hook,
        payoff=payoff,
        publish=publish,
    )


def _run_user_slot(
    user_id: int,
    slot: str,
    *,
    slot_index: int | None = None,
    theme: str | None = None,
    title: str | None = None,
    hook: str | None = None,
    payoff: str | None = None,
    publish: bool = True,
) -> dict:
    with get_session() as session:
        user = session.get(User, user_id)
    if not user or not user.is_active:
        return {"error": "account not active"}
    agent = build_agent_for_user(user)
    if not agent:
        return {"error": "no business profile configured"}
    try:
        if slot == "linkedin":
            results = agent.run_linkedin_slot(slot_index=slot_index)
            if user.enable_engagement and results.get(Platform.linkedin) and results[Platform.linkedin].ok:
                delay = max(1, user.engagement_delay_minutes) * 60
                threading.Timer(delay, _run_user_engagement, args=(user_id,)).start()
        elif slot == "instagram":
            results = agent.run_instagram_slot()
        elif slot == "medium":
            results = agent.run_medium_slot()
        elif slot == "longform_video":
            results = agent.run_longform_video_slot(
                theme=theme,
                manual=LongFormManualBrief(
                    topic=theme,
                    title=title,
                    hook=hook,
                    payoff=payoff,
                ),
                publish=publish,
            )
        else:
            return {"error": f"unknown slot {slot}"}
    finally:
        agent.close()
    _record_results(user_id, results)
    return {p.value: {"ok": r.ok, "permalink": r.permalink, "error": r.error} for p, r in results.items()}


def _record_results(user_id: int, results: dict) -> None:
    with get_session() as session:
        for platform, res in results.items():
            session.add(
                PostLogRow(
                    user_id=user_id,
                    platform=platform.value,
                    ok=res.ok,
                    permalink=res.permalink,
                    error=res.error,
                )
            )
        session.commit()


def _run_user_engagement(user_id: int) -> None:
    with get_session() as session:
        user = session.get(User, user_id)
    if not user or not user.is_active or not user.enable_engagement:
        return
    agent = build_agent_for_user(user)
    if not agent:
        return
    try:
        count = agent.engage_after_linkedin_post()
        logger.info("Hosted LinkedIn engagement for user %s posted %s comments.", user_id, count)
    except Exception:  # noqa: BLE001
        logger.exception("Hosted LinkedIn engagement failed for user %s.", user_id)
    finally:
        agent.close()


# ---- scheduling -------------------------------------------------------
def tick() -> None:
    """Called every minute by the background scheduler."""
    with get_session() as session:
        users = session.exec(select(User).where(User.is_active == True)).all()  # noqa: E712

    for user in users:
        daily_media_plan = _daily_media_plan_for_user(user.id)
        try:
            tz = ZoneInfo(user.timezone or "UTC")
        except Exception:  # noqa: BLE001
            tz = ZoneInfo("UTC")
        now = datetime.now(tz)
        now_hm = now.strftime("%H:%M")
        for action in scheduled_actions_for_user(user, now_hm, daily_media_plan=daily_media_plan):
            logger.info("Reachly %s slot reached for user %s.", action, user.id)
            try:
                if action == "linkedin":
                    run_user_linkedin_slot(
                        user.id,
                        slot_index=_slot_index_for_time(user.post_times or user.post_time, now_hm),
                    )
                elif action == "instagram":
                    run_user_instagram_slot(user.id)
                elif action == "medium":
                    run_user_medium_slot(user.id)
                elif action == "longform_video":
                    run_user_longform_video_slot(user.id)
            except Exception:  # noqa: BLE001
                logger.exception("%s run failed for user %s", action, user.id)


def scheduled_actions_for_user(
    user: User,
    now_hm: str,
    *,
    daily_media_plan: list[str] | None = None,
) -> list[str]:
    linkedin_times = _parse_times(user.post_times or user.post_time or "09:30")
    medium_times = _parse_times(user.medium_times or "")
    instagram_times = instagram_times_for(
        _social_times_for_media_plan(linkedin_times, daily_media_plan or []),
        int(user.instagram_offset_minutes or 0),
    )
    actions = []
    if now_hm in linkedin_times:
        slot_index = _slot_index_for_time(user.post_times or user.post_time, now_hm)
        actions.append(_scheduled_post_action(daily_media_plan or [], slot_index))
    if now_hm in instagram_times:
        actions.append("instagram")
    if now_hm in medium_times:
        actions.append("medium")
    if user.longform_video_enabled and now_hm in _parse_times(user.longform_video_times or ""):
        actions.append("longform_video")
    return actions


def _parse_times(value: str) -> list[str]:
    out = []
    for item in (value or "").replace(" ", "").split(","):
        if not item:
            continue
        parts = item.split(":")
        if len(parts) != 2:
            continue
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            out.append(f"{hour:02d}:{minute:02d}")
    return out


def _slot_index_for_time(value: str, now_hm: str) -> int | None:
    times = _parse_times(value or "")
    try:
        return times.index(now_hm)
    except ValueError:
        return None


def _media_plan(value: str | None) -> list[str]:
    aliases = {
        "image": "image",
        "longform": "longform_video",
        "longform_video": "longform_video",
        "long-form": "longform_video",
        "long-form-video": "longform_video",
        "video": "short_video",
        "vertical": "short_video",
        "vertical_video": "short_video",
        "vertical-video": "short_video",
        "short_video": "short_video",
        "short-video": "short_video",
    }
    plan = [
        aliases[item]
        for item in (raw.strip().lower() for raw in (value or "").split(","))
        if item in aliases
    ]
    if plan == ["image", "image", "image", "short_video", "short_video"]:
        return ["image", "image", "image", "longform_video", "short_video", "image"]
    return plan


def _daily_media_plan_for_user(user_id: int) -> list[str]:
    with get_session() as session:
        user = session.get(User, user_id)
        profile = session.exec(
            select(BusinessProfileRow).where(BusinessProfileRow.user_id == user_id)
        ).first()
    if not profile:
        return []
    providers = decrypt_dict(profile.providers_vault) if profile.providers_vault else {}
    use_server_env = _server_env_fallback_allowed(user, get_settings()) if user else False
    media_plan = _media_plan(
        _provider_value(
            providers,
            "daily_media_plan",
            "REACHLY_DAILY_MEDIA_PLAN",
            use_env=use_server_env,
        )
    )
    video_provider = _provider_value(
        providers,
        "video_provider",
        "VIDEO_PROVIDER",
        default=profile.video_provider,
        use_env=use_server_env,
    )
    if not media_plan and video_provider != "none":
        return ["image", "image", "image", "longform_video", "short_video", "image"]
    return media_plan


def _social_times_for_media_plan(times: list[str], media_plan: list[str]) -> list[str]:
    return [
        time
        for index, time in enumerate(times)
        if _scheduled_post_action(media_plan, index) == "linkedin"
    ]


def _scheduled_post_action(media_plan: list[str], slot_index: int | None) -> str:
    if not media_plan or slot_index is None:
        return "linkedin"
    item = media_plan[slot_index % len(media_plan)]
    if item == "longform_video":
        return "longform_video"
    return "linkedin"


def _as_int(value, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _as_bool(value, default: bool) -> bool:
    if value in (None, ""):
        return default
    return str(value).lower() in ("1", "yes", "true")


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(tick, "cron", minute="*", id="reachly_saas_tick", max_instances=1, coalesce=True)
    sched.start()
    logger.info("Orchestrator scheduler started (per-minute tick).")
    return sched
