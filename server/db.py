"""Database models (SQLModel) for the SaaS server."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, Session, SQLModel, create_engine

from .settings import get_settings

_settings = get_settings()
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
engine = create_engine(_settings.database_url, echo=False, connect_args=_connect_args)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    telegram_chat_id: str = Field(index=True, unique=True)
    telegram_username: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    plan: str = "free"                 # free | pro
    is_active: bool = False            # gated by payment unless free_mode
    license_key: Optional[str] = Field(default=None, index=True)  # for self-host installs

    # posting schedule
    post_time: str = "09:30"
    timezone: str = "UTC"
    attach_image: bool = True
    dry_run: bool = True               # users start in dry-run until they confirm
    enable_engagement: bool = False
    engagement_delay_minutes: int = 30
    engagement_max_comments: int = 3


class BusinessProfileRow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str = "My Business"
    website: Optional[str] = None
    sector: Optional[str] = None
    vision: Optional[str] = None
    product_info: Optional[str] = None
    brand_voice: str = "Confident, helpful, and human. No hype."
    content_themes: str = ""           # comma-separated
    default_hashtags: str = ""         # space/comma separated
    language: str = "English"

    # provider settings (the user's OWN keys — encrypted blob)
    llm_provider: str = "gemini"
    image_provider: str = "gemini"
    video_provider: str = "none"
    providers_vault: str = ""          # encrypted JSON: api keys for llm/media

    # strategy context (company-specific, not Hygaar-specific)
    goals: str = ""                    # highest-priority direction for the agent
    context_repo: Optional[str] = None  # optional repo path with AGENTS.md/product_theory.md
    posting_style: str = "thought_leader"


class PlatformCredRow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    platform: str                       # twitter | linkedin | instagram
    mode: str = "off"                   # api | browser | off
    vault: str = ""                     # encrypted JSON of secrets


class OtpRow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    telegram_chat_id: str = Field(index=True)
    code: str
    expires_at: datetime
    consumed: bool = False


class PostLogRow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    platform: str
    ok: bool
    permalink: Optional[str] = None
    error: Optional[str] = None
    hook: Optional[str] = None


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_sqlite()


def _migrate_sqlite() -> None:
    """Apply tiny additive SQLite migrations for early self-host/SaaS installs."""
    if not _settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(businessprofilerow)").fetchall()
        existing = {row[1] for row in rows}
        additions = {
            "goals": "TEXT NOT NULL DEFAULT ''",
            "context_repo": "VARCHAR",
            "posting_style": "VARCHAR NOT NULL DEFAULT 'thought_leader'",
        }
        for column, ddl in additions.items():
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE businessprofilerow ADD COLUMN {column} {ddl}")
        user_rows = conn.exec_driver_sql("PRAGMA table_info(user)").fetchall()
        user_existing = {row[1] for row in user_rows}
        user_additions = {
            "enable_engagement": "BOOLEAN NOT NULL DEFAULT 0",
            "engagement_delay_minutes": "INTEGER NOT NULL DEFAULT 30",
            "engagement_max_comments": "INTEGER NOT NULL DEFAULT 3",
        }
        for column, ddl in user_additions.items():
            if column not in user_existing:
                conn.exec_driver_sql(f"ALTER TABLE user ADD COLUMN {column} {ddl}")


def get_session() -> Session:
    return Session(engine)
