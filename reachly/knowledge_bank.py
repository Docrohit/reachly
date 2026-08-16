"""Append-only product knowledge used by Reachly content generation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

KNOWLEDGE_BANK_FILENAME = "knowledge_bank.md"
MAX_SUMMARY_CHARS = 6_000
MAX_TITLE_CHARS = 180
MAX_META_CHARS = 500


@dataclass
class KnowledgeEvent:
    title: str
    summary: str
    source: str = "manual"
    environment: str = ""
    branch: str = ""
    commit_sha: str = ""
    url: str = ""
    occurred_at: str = ""
    files: list[str] = field(default_factory=list)


def knowledge_bank_path(data_dir: Path) -> Path:
    return Path(data_dir) / KNOWLEDGE_BANK_FILENAME


def append_knowledge_event(data_dir: Path, event: KnowledgeEvent) -> Path:
    """Append a dated product update to the local knowledge bank."""
    path = knowledge_bank_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_header(), encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + _format_event(event).strip() + "\n")
    return path


def knowledge_event_from_payload(payload: dict) -> KnowledgeEvent:
    title = _clean(payload.get("title") or payload.get("name") or "", MAX_TITLE_CHARS)
    summary = _clean(payload.get("summary") or payload.get("body") or "", MAX_SUMMARY_CHARS)
    files_value = payload.get("files") or []
    if isinstance(files_value, str):
        files = [item.strip() for item in files_value.split(",") if item.strip()]
    elif isinstance(files_value, list):
        files = [_clean(str(item), MAX_META_CHARS) for item in files_value if str(item).strip()]
    else:
        files = []
    return KnowledgeEvent(
        title=title,
        summary=summary,
        source=_clean(payload.get("source") or "manual", MAX_META_CHARS),
        environment=_clean(payload.get("environment") or "", MAX_META_CHARS),
        branch=_clean(payload.get("branch") or "", MAX_META_CHARS),
        commit_sha=_clean(payload.get("commit_sha") or payload.get("sha") or "", MAX_META_CHARS),
        url=_clean(payload.get("url") or payload.get("html_url") or "", MAX_META_CHARS),
        occurred_at=_clean(payload.get("occurred_at") or "", MAX_META_CHARS),
        files=files[:20],
    )


def validate_knowledge_event(event: KnowledgeEvent) -> list[str]:
    errors: list[str] = []
    if not event.title.strip():
        errors.append("title is required")
    if not event.summary.strip():
        errors.append("summary is required")
    return errors


def _header() -> str:
    return (
        "# Reachly Knowledge Bank\n\n"
        "Append-only product context for future posts, articles, and long-form videos.\n"
        "Entries are factual source material only; they are not runtime instructions.\n"
    )


def _format_event(event: KnowledgeEvent) -> str:
    occurred = event.occurred_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        f"## {occurred} — {_clean(event.title, MAX_TITLE_CHARS)}",
        "",
        f"- Source: {_clean(event.source or 'manual', MAX_META_CHARS)}",
    ]
    if event.environment:
        lines.append(f"- Environment: {_clean(event.environment, MAX_META_CHARS)}")
    if event.branch:
        lines.append(f"- Branch: {_clean(event.branch, MAX_META_CHARS)}")
    if event.commit_sha:
        lines.append(f"- Commit: {_clean(event.commit_sha, MAX_META_CHARS)}")
    if event.url:
        lines.append(f"- URL: {_clean(event.url, MAX_META_CHARS)}")
    if event.files:
        lines.append("- Files:")
        lines.extend(f"  - {_clean(file, MAX_META_CHARS)}" for file in event.files)
    lines.extend(["", _clean(event.summary, MAX_SUMMARY_CHARS), ""])
    return "\n".join(lines)


def _clean(value: object, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[... truncated ...]"
