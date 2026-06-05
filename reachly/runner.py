"""Standalone entrypoint."""
from __future__ import annotations

import argparse
import logging
import sys

from .agent import Agent
from .config import AgentConfig
from .models import Platform
from .scheduler import run_daily
from .settings_store import (
    instagram_times_for,
    parse_instagram_offset,
    parse_post_times,
)


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(prog="reachly", description="Reachly thought-leadership agent")
    parser.add_argument(
        "command",
        choices=["once", "run", "preview", "linkedin", "instagram", "twitter", "analytics", "engage"],
        help=(
            "once=all enabled | linkedin=LinkedIn only | instagram=IG test | twitter=X test | "
            "analytics=print recent performance context | run=scheduler | preview=dry-run"
        ),
    )
    parser.add_argument("--theme", default=None, help="override today's theme")
    parser.add_argument("--env", default=".env", help="path to .env file")
    parser.add_argument("--post-id", type=int, default=None, help="post id for analytics updates")
    parser.add_argument("--impressions", type=int, default=None, help="analytics impressions")
    parser.add_argument("--likes", type=int, default=None, help="analytics likes/reactions")
    parser.add_argument("--comments", type=int, default=None, help="analytics comments")
    parser.add_argument("--shares", type=int, default=None, help="analytics shares/reposts")
    parser.add_argument("--note", default=None, help="qualitative analytics note")
    args = parser.parse_args(argv)

    cfg = AgentConfig.from_env_file(args.env)
    if args.command == "preview":
        cfg.dry_run = True

    agent = Agent.from_config(cfg)
    li_times = parse_post_times(cfg.post_times_raw, cfg.data_dir)
    ig_offset = parse_instagram_offset(cfg.instagram_offset_minutes, cfg.data_dir)
    ig_times = instagram_times_for(li_times, ig_offset)

    if args.command == "preview":
        agent.run_once(theme=args.theme)
        agent.close()
        return 0

    if args.command == "once":
        agent.run_once(theme=args.theme)
        agent.close()
        return 0

    if args.command == "linkedin":
        agent.run_once(theme=args.theme, platforms=[Platform.linkedin])
        agent.close()
        return 0

    if args.command == "instagram":
        # Simulate the daily Instagram slot (pending post + image + IG only)
        if args.theme:
            agent.run_linkedin_slot(theme=args.theme)
        agent.run_instagram_slot()
        agent.close()
        return 0

    if args.command == "twitter":
        agent.run_once(theme=args.theme, platforms=[Platform.twitter])
        agent.close()
        return 0

    if args.command == "engage":
        count = agent.engage_after_linkedin_post()
        print(f"LinkedIn engagement comments posted: {count}")
        agent.close()
        return 0

    if args.command == "analytics":
        if args.post_id is not None:
            agent.history.record_analytics(
                args.post_id,
                impressions=args.impressions,
                likes=args.likes,
                comments=args.comments,
                shares=args.shares,
                note=args.note,
            )
            print(f"Updated analytics for post {args.post_id}.")
        print(agent.analytics_review())
        agent.close()
        return 0

    run_daily(
        agent,
        linkedin_times=li_times,
        instagram_times=ig_times if agent.platforms[Platform.instagram].enabled else [],
        timezone=cfg.timezone,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
