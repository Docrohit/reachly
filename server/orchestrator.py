"""Per-user orchestration for the hosted product.

Maps DB rows -> the agent's domain objects, runs the agent, and records results.
A background scheduler checks every minute for users whose local posting time has
arrived.
"""
from __future__ import annotations

import logging
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
    media_plan = _media_plan(providers.get("daily_media_plan"))
    if not media_plan and profile_row.video_provider != "none":
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
        platforms[platform] = _creds_from_secrets(platform, PlatformMode(row.mode), secrets)

    data_dir = Path(settings.media_dir).parent / "agents" / f"user_{user.id}"
    global_knowledge_bank = knowledge_bank_path(Path(settings.media_dir).parent / "knowledge")
    context_doc_paths = [str(global_knowledge_bank)] if global_knowledge_bank.is_file() else []
    agent_settings = AgentSettings(
        llm_provider=profile_row.llm_provider,
        gemini_api_key=providers.get("gemini_api_key"),
        openai_api_key=providers.get("openai_api_key"),
        anthropic_api_key=providers.get("anthropic_api_key"),
        image_provider=profile_row.image_provider,
        gemini_image_model=providers.get("gemini_image_model", "gemini-2.5-flash-image"),
        video_provider=profile_row.video_provider,
        hygaar_base_url=providers.get("hygaar_base_url"),
        hygaar_api_token=providers.get("hygaar_api_token"),
        seedance_api_key=providers.get("seedance_api_key"),
        seedance_base_url=providers.get(
            "seedance_base_url",
            "https://ark.ap-southeast.bytepluses.com/api/v3",
        ),
        seedance_model=providers.get("seedance_model", "seedance_2_5"),
        seedance_fallback_model=providers.get("seedance_fallback_model", "seedance_2_0"),
        seedance_ratio=providers.get("seedance_ratio", "9:16"),
        seedance_target_duration=_as_int(providers.get("seedance_target_duration"), 30),
        seedance_clip_count=_as_int(providers.get("seedance_clip_count"), 0),
        seedance_clip_duration=_as_int(providers.get("seedance_clip_duration"), 15),
        seedance_generate_audio=_as_bool(providers.get("seedance_generate_audio"), True),
        seedance_watermark=_as_bool(providers.get("seedance_watermark"), False),
        longform_video_enabled=user.longform_video_enabled,
        longform_video_target_seconds=_as_int(providers.get("longform_video_target_seconds"), 90),
        longform_video_card_seconds=_as_int(providers.get("longform_video_card_seconds"), 18),
        longform_video_max_card_retries=_as_int(providers.get("longform_video_max_card_retries"), 2),
        longform_video_title_alignment_threshold=_as_int(
            providers.get("longform_video_title_alignment_threshold"),
            7,
        ),
        longform_video_qc_enabled=_as_bool(providers.get("longform_video_qc_enabled"), True),
        longform_video_qc_model=providers.get("longform_video_qc_model", "gemini-2.5-flash"),
        openai_transcription_model=providers.get("openai_transcription_model", "gpt-4o-transcribe"),
        openai_transcription_fallback_model=providers.get(
            "openai_transcription_fallback_model",
            "whisper-1",
        ),
        elevenlabs_api_key=providers.get("elevenlabs_api_key"),
        elevenlabs_voice_id=providers.get("elevenlabs_voice_id", "JBFqnCBsd6RMkjVDRZzb"),
        elevenlabs_model=providers.get("elevenlabs_model", "eleven_v3"),
        elevenlabs_output_format=providers.get("elevenlabs_output_format", "mp3_44100_128"),
        daily_media_plan=media_plan,
        brand_logo_path=providers.get("brand_logo_path"),
        brand_logo_position=providers.get("brand_logo_position", "bottom-right"),
        attach_image=user.attach_image,
        dry_run=user.dry_run,
        data_dir=data_dir,
        public_media_base_url=settings.public_media_url,
        public_media_dir=Path(settings.media_dir),
        context_repo=profile_row.context_repo,
        context_doc_paths=context_doc_paths,
        posting_style=profile_row.posting_style,
        enable_engagement=user.enable_engagement,
        engagement_delay_minutes=user.engagement_delay_minutes,
        engagement_max_comments=user.engagement_max_comments,
        text_platform_image_rate=float(providers.get("text_platform_image_rate", 0.5)),
        linkedin_image_rate=(
            float(providers["linkedin_image_rate"])
            if providers.get("linkedin_image_rate")
            else None
        ),
        twitter_image_rate=(
            float(providers["twitter_image_rate"])
            if providers.get("twitter_image_rate")
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


def _creds_from_secrets(platform: Platform, mode: PlatformMode, s: dict) -> PlatformCredentials:
    if platform == Platform.twitter:
        return PlatformCredentials(
            platform=platform, mode=mode,
            api_token=s.get("oauth2_token"),
            extra={
                "login_identifier": s.get("login_identifier", ""),
                "consumer_key": s.get("consumer_key", ""),
                "consumer_secret": s.get("consumer_secret", ""),
                "access_token": s.get("access_token", ""),
                "access_token_secret": s.get("access_token_secret", ""),
            },
            username=s.get("username"), password=s.get("password"),
        )
    if platform == Platform.linkedin:
        return PlatformCredentials(
            platform=platform, mode=mode,
            api_token=s.get("access_token"),
            extra={
                "person_urn": s.get("person_urn", ""),
                "organization_id": s.get("organization_id", ""),
                "post_as": s.get("post_as", ""),
                "company_admin_url": s.get("company_admin_url", ""),
            },
            username=s.get("email"), password=s.get("password"),
        )
    if platform == Platform.instagram:
        return PlatformCredentials(
            platform=platform, mode=mode,
            api_token=s.get("access_token"),
            extra={"user_id": s.get("user_id", "")},
            username=s.get("username"), password=s.get("password"),
        )
    if platform == Platform.medium:
        return PlatformCredentials(
            platform=platform,
            mode=mode,
            extra={
                "publish_status": s.get("publish_status", "draft"),
                "expected_account": s.get("expected_account", ""),
            },
            username=s.get("email"),
            password=s.get("password"),
        )
    if platform == Platform.youtube:
        return PlatformCredentials(
            platform=platform,
            mode=mode,
            api_token=s.get("access_token"),
            extra={
                "refresh_token": s.get("refresh_token", ""),
                "client_id": s.get("client_id", ""),
                "client_secret": s.get("client_secret", ""),
                "token_uri": s.get("token_uri", "https://oauth2.googleapis.com/token"),
                "privacy_status": s.get("privacy_status", "private"),
                "category_id": s.get("category_id", "22"),
                "notify_subscribers": s.get("notify_subscribers", "false"),
                "default_tags": s.get("default_tags", ""),
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
        profile = session.exec(
            select(BusinessProfileRow).where(BusinessProfileRow.user_id == user_id)
        ).first()
    if not profile:
        return []
    providers = decrypt_dict(profile.providers_vault) if profile.providers_vault else {}
    media_plan = _media_plan(providers.get("daily_media_plan"))
    if not media_plan and profile.video_provider != "none":
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
