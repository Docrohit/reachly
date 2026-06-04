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
        choices=["once", "run", "preview", "instagram", "twitter"],
        help="once=all enabled | instagram=IG test | twitter=X test | run=scheduler | preview=dry-run",
    )
    parser.add_argument("--theme", default=None, help="override today's theme")
    parser.add_argument("--env", default=".env", help="path to .env file")
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

    run_daily(
        agent,
        linkedin_times=li_times,
        instagram_times=ig_times if agent.platforms[Platform.instagram].enabled else [],
        timezone=cfg.timezone,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
