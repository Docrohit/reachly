"""Scheduler: LinkedIn at POST_TIMES; Instagram N minutes later (with image)."""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .agent import Agent

logger = logging.getLogger("reachly.scheduler")


def run_daily(
    agent: Agent,
    *,
    linkedin_times: list[str],
    instagram_times: list[str],
    timezone: str,
) -> None:
    sched = BlockingScheduler(timezone=timezone)

    for pt in linkedin_times:
        h, m = (int(x) for x in pt.strip().split(":"))

        def _li_job(hour=h, minute=m, slot=pt):
            logger.info("LinkedIn trigger at %s (%s).", slot, timezone)
            try:
                agent.run_linkedin_slot()
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

    logger.info(
        "Reachly scheduled — LinkedIn: %s | Instagram: %s (%s)",
        ", ".join(linkedin_times),
        ", ".join(instagram_times),
        timezone,
    )
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        agent.close()
