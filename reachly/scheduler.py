"""Scheduler: LinkedIn at POST_TIMES; Instagram N minutes later (with image)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .agent import Agent
from .models import Platform

logger = logging.getLogger("reachly.scheduler")


def run_daily(
    agent: Agent,
    *,
    linkedin_times: list[str],
    instagram_times: list[str],
    medium_times: list[str],
    longform_video_times: list[str] | None = None,
    timezone: str,
) -> None:
    sched = BlockingScheduler(timezone=timezone)

    for slot_index, pt in enumerate(linkedin_times):
        h, m = (int(x) for x in pt.strip().split(":"))

        def _li_job(hour=h, minute=m, slot=pt, index=slot_index):
            logger.info("LinkedIn trigger at %s (%s).", slot, timezone)
            try:
                results = agent.run_linkedin_slot(slot_index=index)
                if (
                    agent.settings.enable_engagement
                    and results.get(Platform.linkedin)
                    and results[Platform.linkedin].ok
                ):
                    run_at = datetime.now(ZoneInfo(timezone)) + timedelta(
                        minutes=agent.settings.engagement_delay_minutes
                    )
                    agent.schedule_linkedin_engagement(run_at)
                    logger.info(
                        "Scheduled LinkedIn engagement follow-up for %s (%s).",
                        run_at.isoformat(),
                        timezone,
                    )
            except Exception as e:  # noqa: BLE001
                message = f"LinkedIn run failed at {slot}: {e}"
                logger.exception(message)
                agent.history.record_event(platform="linkedin", ok=False, error=message)

        sched.add_job(
            _li_job,
            CronTrigger(hour=h, minute=m, timezone=timezone),
            id=f"linkedin-{pt}",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=900,
        )

    def _engagement_job():
        try:
            count = agent.run_due_engagement()
            if count:
                logger.info("LinkedIn engagement follow-up complete: %s comments.", count)
        except Exception as e:  # noqa: BLE001
            message = f"LinkedIn engagement follow-up failed: {e}"
            logger.exception(message)
            agent.history.record_event(platform="linkedin", ok=False, error=message)

    sched.add_job(
        _engagement_job,
        CronTrigger(minute="*", timezone=timezone),
        id="linkedin-engagement-due-check",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=900,
    )

    for pt in instagram_times:
        h, m = (int(x) for x in pt.strip().split(":"))

        def _ig_job(hour=h, minute=m, slot=pt):
            logger.info("Instagram trigger at %s (%s).", slot, timezone)
            try:
                agent.run_instagram_slot()
            except Exception as e:  # noqa: BLE001
                message = f"Instagram run failed at {slot}: {e}"
                logger.exception(message)
                agent.history.record_event(platform="instagram", ok=False, error=message)

        sched.add_job(
            _ig_job,
            CronTrigger(hour=h, minute=m, timezone=timezone),
            id=f"instagram-{pt}",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=900,
        )

    for pt in medium_times:
        h, m = (int(x) for x in pt.strip().split(":"))

        def _medium_job(hour=h, minute=m, slot=pt):
            logger.info("Medium trigger at %s (%s).", slot, timezone)
            try:
                agent.run_medium_slot()
            except Exception as e:  # noqa: BLE001
                message = f"Medium run failed at {slot}: {e}"
                logger.exception(message)
                agent.history.record_event(platform="medium", ok=False, error=message)

        sched.add_job(
            _medium_job,
            CronTrigger(hour=h, minute=m, timezone=timezone),
            id=f"medium-{pt}",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=900,
        )

    for pt in longform_video_times or []:
        h, m = (int(x) for x in pt.strip().split(":"))

        def _longform_job(hour=h, minute=m, slot=pt):
            logger.info("Long-form video trigger at %s (%s).", slot, timezone)
            try:
                agent.run_longform_video_slot()
            except Exception as e:  # noqa: BLE001
                message = f"Long-form video run failed at {slot}: {e}"
                logger.exception(message)
                agent.history.record_event(platform="longform_video", ok=False, error=message)

        sched.add_job(
            _longform_job,
            CronTrigger(hour=h, minute=m, timezone=timezone),
            id=f"longform-video-{pt}",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=900,
        )

    logger.info(
        "Reachly scheduled — LinkedIn: %s | Instagram: %s | Medium: %s | Long-form video: %s (%s)",
        ", ".join(linkedin_times),
        ", ".join(instagram_times),
        ", ".join(medium_times),
        ", ".join(longform_video_times or []),
        timezone,
    )
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        agent.close()
