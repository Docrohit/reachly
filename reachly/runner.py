"""Standalone entrypoint."""
from __future__ import annotations

import argparse
import logging
import shutil
import sys

from .agent import Agent
from .config import AgentConfig
from .longform_video import LongFormManualBrief
from .media import SeedanceClient
from .models import Platform
from .scheduler import run_daily
from .settings_store import (
    instagram_times_for,
    parse_longform_video_times,
    parse_instagram_offset,
    parse_post_times,
)


def _parse_times(value: str) -> list[str]:
    return [t.strip() for t in (value or "").split(",") if t.strip()]


def _results_exit_code(results: dict) -> int:
    return 2 if any(not result.ok for result in results.values()) else 0


def _has_browser_session(cfg: AgentConfig, platform: str) -> bool:
    session_dir = cfg.data_dir / "browser_sessions" / platform
    try:
        return session_dir.is_dir() and any(session_dir.iterdir())
    except OSError:
        return False


def _video_preflight(cfg: AgentConfig, *, include_instagram: bool = False) -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(
        (
            "video_provider",
            cfg.video_provider == "seedance",
            f"expected seedance, got {cfg.video_provider}",
        )
    )
    checks.append(
        (
            "seedance_api_key",
            bool(cfg.seedance_api_key),
            "missing SEEDANCE_API_KEY, ARK_API_KEY, or MODELARK_API_KEY",
        )
    )
    checks.append(
        (
            "seedance_model",
            cfg.seedance_model == "seedance_2_5",
            f"expected seedance_2_5, got {cfg.seedance_model}",
        )
    )
    checks.append(
        (
            "seedance_fallback_model",
            cfg.seedance_fallback_model == "seedance_2_0",
            f"expected seedance_2_0, got {cfg.seedance_fallback_model}",
        )
    )
    checks.append(("dry_run", not cfg.dry_run, "DRY_RUN must be no/off/false for a live post"))
    linkedin = cfg.platforms[Platform.linkedin]
    checks.append(("linkedin_enabled", linkedin.enabled, "LINKEDIN_MODE is off"))
    checks.append(
        (
            "linkedin_browser",
            linkedin.mode.value == "browser",
            f"expected browser mode, got {linkedin.mode.value}",
        )
    )
    checks.append(
        (
            "linkedin_login",
            bool(linkedin.username and linkedin.password) or _has_browser_session(cfg, "linkedin"),
            "missing browser login credentials or persistent LinkedIn session",
        )
    )
    if include_instagram:
        instagram = cfg.platforms[Platform.instagram]
        checks.append(("instagram_enabled", instagram.enabled, "INSTAGRAM_MODE is off"))
        checks.append(
            (
                "instagram_browser",
                instagram.mode.value == "browser",
                f"expected browser mode, got {instagram.mode.value}",
            )
        )
        checks.append(
            (
                "instagram_login",
                bool(instagram.username and instagram.password) or _has_browser_session(cfg, "instagram"),
                "missing Instagram browser username/password or persistent Instagram session",
            )
        )

    ok = True
    for name, passed, detail in checks:
        marker = "ok" if passed else "missing"
        print(f"{marker:7} {name}")
        if not passed:
            print(f"        {detail}")
            ok = False
    return 0 if ok else 2


def _seedance_account_check(cfg: AgentConfig, *, duration: int = 4) -> int:
    if not cfg.seedance_api_key:
        print("missing seedance_api_key")
        print("        missing SEEDANCE_API_KEY, ARK_API_KEY, or MODELARK_API_KEY")
        return 2

    client = SeedanceClient(
        cfg.seedance_api_key,
        base_url=cfg.seedance_base_url,
        model_key=cfg.seedance_model,
        fallback_model_key=cfg.seedance_fallback_model,
        poll_interval=0,
        max_poll_attempts=1,
    )
    models = [cfg.seedance_model]
    if cfg.seedance_fallback_model and cfg.seedance_fallback_model not in models:
        models.append(cfg.seedance_fallback_model)

    ok = True
    probe_duration = max(4, min(15, int(duration or 4)))
    for model_key in models:
        try:
            client._create_task(
                model_key,
                "Reachly Seedance account readiness check. Simple product-media motion test.",
                ratio=cfg.seedance_ratio,
                duration=probe_duration,
                generate_audio=False,
                watermark=False,
            )
            print(f"ok      {model_key}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"blocked {model_key}")
            print(f"        {str(exc)[:260]}")
    return 0 if ok else 2


def _longform_video_preflight(cfg: AgentConfig) -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("ffmpeg", bool(shutil.which("ffmpeg")), "ffmpeg is required for render/QC frames"))
    checks.append(("ffprobe", bool(shutil.which("ffprobe")), "ffprobe is required for audio/video timing"))
    checks.append(("seedance_api_key", bool(cfg.seedance_api_key), "missing SEEDANCE_API_KEY, ARK_API_KEY, or MODELARK_API_KEY"))
    checks.append(("elevenlabs_api_key", bool(cfg.elevenlabs_api_key), "missing ELEVENLABS_API_KEY"))
    checks.append(("openai_api_key", bool(cfg.openai_api_key), "missing OPENAI_API_KEY for gpt-4o-transcribe/whisper fallback"))
    checks.append(("gemini_api_key", bool(cfg.gemini_api_key) or not cfg.longform_video_qc_enabled, "missing GEMINI_API_KEY for clip hallucination QC"))
    linkedin = cfg.platforms[Platform.linkedin]
    youtube = cfg.platforms[Platform.youtube]
    checks.append(("linkedin_enabled", linkedin.enabled, "LINKEDIN_MODE is off"))
    checks.append(("youtube_enabled", youtube.enabled, "YOUTUBE_MODE is off"))
    checks.append(("youtube_api_mode", youtube.mode.value in ("api", "off"), "YouTube long-form posting supports API mode only"))
    if youtube.enabled:
        has_oauth = bool(
            youtube.extra.get("refresh_token")
            and youtube.extra.get("client_id")
            and youtube.extra.get("client_secret")
        )
        checks.append(
            (
                "youtube_oauth",
                has_oauth or bool(youtube.api_token),
                "need YOUTUBE_REFRESH_TOKEN + YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET, or YOUTUBE_ACCESS_TOKEN",
            )
        )

    ok = True
    for name, passed, detail in checks:
        marker = "ok" if passed else "missing"
        print(f"{marker:7} {name}")
        if not passed:
            print(f"        {detail}")
            ok = False
    return 0 if ok else 2


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(prog="reachly", description="Reachly thought-leadership agent")
    parser.add_argument(
        "command",
        choices=[
            "once",
            "run",
            "preview",
            "linkedin",
            "instagram",
            "twitter",
            "medium",
            "video-test",
            "video-preflight",
            "longform-video",
            "longform-video-preflight",
            "seedance-account-check",
            "analytics",
            "engage",
        ],
        help=(
            "once=all enabled | linkedin=LinkedIn only | instagram=IG test | twitter=X test | medium=Medium article | "
            "video-test=one video to LinkedIn+Instagram only | video-preflight=check live video config | "
            "longform-video=one narration-led 16:9 video to LinkedIn+YouTube | "
            "longform-video-preflight=check long-form video config | "
            "seedance-account-check=probe Seedance model activation/billing with minimal tasks | "
            "analytics=print recent performance context | run=scheduler | preview=dry-run"
        ),
    )
    parser.add_argument("--theme", default=None, help="override today's theme")
    parser.add_argument("--longform-title", default=None, help="manual title for long-form video")
    parser.add_argument("--longform-hook", default=None, help="manual opening hook for long-form video")
    parser.add_argument("--longform-payoff", default=None, help="manual closing payoff/CTA for long-form video")
    parser.add_argument(
        "--media-kind",
        choices=["auto", "image", "video"],
        default="auto",
        help="force image or video generation for one-shot test commands",
    )
    parser.add_argument(
        "--video-strategy",
        choices=["auto", "recap", "fresh"],
        default="auto",
        help="for video runs: recap uses recent image posts; fresh generates new reference images",
    )
    parser.add_argument("--env", default=".env", help="path to .env file")
    parser.add_argument(
        "--include-instagram",
        action="store_true",
        help="include Instagram browser checks in video-preflight",
    )
    parser.add_argument(
        "--seedance-check-duration",
        type=int,
        default=4,
        help="duration in seconds for seedance-account-check probe tasks",
    )
    parser.add_argument("--post-id", type=int, default=None, help="post id for analytics updates")
    parser.add_argument("--impressions", type=int, default=None, help="analytics impressions")
    parser.add_argument("--likes", type=int, default=None, help="analytics likes/reactions")
    parser.add_argument("--comments", type=int, default=None, help="analytics comments")
    parser.add_argument("--shares", type=int, default=None, help="analytics shares/reposts")
    parser.add_argument("--note", default=None, help="qualitative analytics note")
    args = parser.parse_args(argv)

    cfg = AgentConfig.from_env_file(args.env)
    if args.command == "video-preflight":
        return _video_preflight(cfg, include_instagram=args.include_instagram)
    if args.command == "longform-video-preflight":
        return _longform_video_preflight(cfg)
    if args.command == "seedance-account-check":
        return _seedance_account_check(cfg, duration=args.seedance_check_duration)
    if args.command == "preview":
        cfg.dry_run = True

    agent = Agent.from_config(cfg)
    li_times = parse_post_times(cfg.post_times_raw, cfg.data_dir)
    ig_offset = parse_instagram_offset(cfg.instagram_offset_minutes, cfg.data_dir)
    ig_times = instagram_times_for(li_times, ig_offset)
    medium_times = _parse_times(cfg.medium_times_raw)

    if args.command == "preview":
        results = agent.run_once(
            theme=args.theme,
            media_kind=args.media_kind,
            video_strategy=args.video_strategy,
        )
        agent.close()
        return _results_exit_code(results)

    if args.command == "once":
        results = agent.run_once(
            theme=args.theme,
            media_kind=args.media_kind,
            video_strategy=args.video_strategy,
        )
        agent.close()
        return _results_exit_code(results)

    if args.command == "linkedin":
        results = agent.run_once(
            theme=args.theme,
            platforms=[Platform.linkedin],
            media_kind=args.media_kind,
            video_strategy=args.video_strategy,
        )
        agent.close()
        return _results_exit_code(results)

    if args.command == "instagram":
        # Simulate the daily Instagram slot (pending post + image + IG only)
        results = {}
        if args.theme or args.media_kind != "auto":
            results.update(agent.run_linkedin_slot(
                theme=args.theme,
                media_kind=args.media_kind,
                video_strategy=args.video_strategy,
            ))
        results.update(agent.run_instagram_slot())
        agent.close()
        return _results_exit_code(results)

    if args.command == "twitter":
        results = agent.run_once(theme=args.theme, platforms=[Platform.twitter])
        agent.close()
        return _results_exit_code(results)

    if args.command == "medium":
        results = agent.run_medium_slot(theme=args.theme)
        agent.close()
        return _results_exit_code(results)

    if args.command == "video-test":
        results = agent.run_video_test(theme=args.theme, video_strategy=args.video_strategy)
        agent.close()
        return _results_exit_code(results)

    if args.command == "longform-video":
        manual = LongFormManualBrief(
            topic=args.theme,
            title=args.longform_title,
            hook=args.longform_hook,
            payoff=args.longform_payoff,
        )
        results = agent.run_longform_video_slot(theme=args.theme, manual=manual)
        agent.close()
        return _results_exit_code(results)

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
        medium_times=medium_times if agent.platforms[Platform.medium].enabled else [],
        longform_video_times=(
            parse_longform_video_times(cfg.longform_video_times_raw, cfg.data_dir)
            if cfg.longform_video_enabled
            else []
        ),
        timezone=cfg.timezone,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
