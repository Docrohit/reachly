"""Dashboard-editable settings (goals, schedule, posting style) stored beside the agent."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


DEFAULT_POST_TIMES = ["09:00", "13:30", "21:00"]
DEFAULT_INSTAGRAM_OFFSET_MINUTES = 5


def offset_times(times: list[str], minutes: int) -> list[str]:
    """Return HH:MM list with each time shifted by `minutes` (wraps past midnight)."""
    from datetime import datetime, timedelta

    out: list[str] = []
    for t in times:
        h, m = (int(x) for x in t.strip().split(":"))
        dt = datetime(2000, 1, 1, h, m) + timedelta(minutes=minutes)
        out.append(dt.strftime("%H:%M"))
    return out


def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / "dashboard_settings.json"


def goals_path(data_dir: Path) -> Path:
    return Path(data_dir) / "goals.md"


def load_dashboard_settings(data_dir: Path) -> dict:
    path = settings_path(data_dir)
    if not path.is_file():
        return {
            "post_times": list(DEFAULT_POST_TIMES),
            "instagram_offset_minutes": DEFAULT_INSTAGRAM_OFFSET_MINUTES,
            "posting_style": "thought_leader",
            "context_repo": "",
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("post_times", DEFAULT_POST_TIMES)
    data.setdefault("instagram_offset_minutes", DEFAULT_INSTAGRAM_OFFSET_MINUTES)
    data.setdefault("posting_style", "thought_leader")
    data.setdefault("context_repo", "")
    return data


def save_dashboard_settings(
    data_dir: Path,
    *,
    post_times: list[str],
    posting_style: str,
    context_repo: str,
    instagram_offset_minutes: int = DEFAULT_INSTAGRAM_OFFSET_MINUTES,
) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    settings_path(data_dir).write_text(
        json.dumps(
            {
                "post_times": post_times,
                "instagram_offset_minutes": instagram_offset_minutes,
                "posting_style": posting_style,
                "context_repo": context_repo,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def load_goals(data_dir: Path) -> str:
    p = goals_path(data_dir)
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def save_goals(data_dir: Path, text: str) -> None:
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    goals_path(data_dir).write_text(text, encoding="utf-8")


def parse_post_times(value: Optional[str], data_dir: Path) -> list[str]:
    """Dashboard settings override env after first save; env seeds installs."""
    if settings_path(data_dir).is_file():
        return load_dashboard_settings(data_dir).get("post_times", DEFAULT_POST_TIMES)
    if value and value.strip():
        return [t.strip() for t in value.split(",") if t.strip()]
    return DEFAULT_POST_TIMES


def parse_instagram_offset(value: Optional[str], data_dir: Path) -> int:
    if settings_path(data_dir).is_file():
        return int(load_dashboard_settings(data_dir).get("instagram_offset_minutes", DEFAULT_INSTAGRAM_OFFSET_MINUTES))
    if value and str(value).strip().isdigit():
        return int(value)
    return DEFAULT_INSTAGRAM_OFFSET_MINUTES


def instagram_times_for(linkedin_times: list[str], offset_minutes: int) -> list[str]:
    return offset_times(linkedin_times, offset_minutes)
