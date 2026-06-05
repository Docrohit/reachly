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
from reachly.models import (
    BusinessProfile,
    Platform,
    PlatformCredentials,
    PlatformMode,
)

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
        attach_image=user.attach_image,
        dry_run=user.dry_run,
        data_dir=data_dir,
        public_media_base_url=settings.public_media_url,
        context_repo=profile_row.context_repo,
        posting_style=profile_row.posting_style,
        enable_engagement=user.enable_engagement,
        engagement_delay_minutes=user.engagement_delay_minutes,
        engagement_max_comments=user.engagement_max_comments,
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
            extra={"login_identifier": s.get("login_identifier", "")},
            username=s.get("username"), password=s.get("password"),
        )
    if platform == Platform.linkedin:
        return PlatformCredentials(
            platform=platform, mode=mode,
            api_token=s.get("access_token"),
            extra={
                "person_urn": s.get("person_urn", ""),
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
    return {p.value: {"ok": r.ok, "permalink": r.permalink, "error": r.error} for p, r in results.items()}


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
        try:
            tz = ZoneInfo(user.timezone or "UTC")
        except Exception:  # noqa: BLE001
            tz = ZoneInfo("UTC")
        now = datetime.now(tz)
        if now.strftime("%H:%M") == (user.post_time or "09:30"):
            logger.info("Posting time reached for user %s.", user.id)
            try:
                run_user_now(user.id)
            except Exception:  # noqa: BLE001
                logger.exception("Run failed for user %s", user.id)


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(tick, "cron", minute="*", id="reachly_saas_tick", max_instances=1, coalesce=True)
    sched.start()
    logger.info("Orchestrator scheduler started (per-minute tick).")
    return sched
