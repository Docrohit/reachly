"""Server configuration (env-driven)."""
from __future__ import annotations

import os
from functools import lru_cache
from secrets import token_urlsafe


class ServerSettings:
    def __init__(self):
        self.database_url = os.getenv("REACHLY_DATABASE_URL", "sqlite:///./reachly_server.db")
        # Fernet key used to encrypt the credential vault. Generate once with:
        #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
        self.vault_key = os.getenv("REACHLY_VAULT_KEY", "")
        self.session_secret = os.getenv("REACHLY_SESSION_SECRET", "")

        # Telegram bot used for OTP login.
        self.telegram_bot_token = os.getenv("REACHLY_TELEGRAM_BOT_TOKEN", "")
        self.telegram_bot_username = os.getenv("REACHLY_TELEGRAM_BOT_USERNAME", "")
        self.admin_telegram_ids = {
            item.strip()
            for item in os.getenv("REACHLY_ADMIN_TELEGRAM_IDS", "").split(",")
            if item.strip()
        }

        # Where generated media is stored + publicly served (needed by IG API mode).
        self.media_dir = os.getenv("REACHLY_MEDIA_DIR", "./reachly_media")
        self.public_base_url = os.getenv("REACHLY_PUBLIC_BASE_URL", "http://localhost:8000")

        # Billing (optional).
        self.stripe_secret_key = os.getenv("REACHLY_STRIPE_SECRET_KEY", "")
        self.stripe_price_id = os.getenv("REACHLY_STRIPE_PRICE_ID", "")
        self.stripe_webhook_secret = os.getenv("REACHLY_STRIPE_WEBHOOK_SECRET", "")
        # If true, new users are active without paying (useful for local/dev).
        self.free_mode = os.getenv("REACHLY_FREE_MODE", "true").lower() in ("1", "true", "yes")
        self.production = os.getenv("REACHLY_ENVIRONMENT", "development").lower() in (
            "prod",
            "production",
        )

        if not self.session_secret:
            if self.production:
                raise RuntimeError("REACHLY_SESSION_SECRET is required in production.")
            self.session_secret = token_urlsafe(48)

        if self.production and self.free_mode:
            raise RuntimeError("REACHLY_FREE_MODE=true is not allowed in production.")
        if self.production and not self.vault_key:
            raise RuntimeError("REACHLY_VAULT_KEY is required in production.")

    @property
    def public_media_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/media"


@lru_cache
def get_settings() -> ServerSettings:
    return ServerSettings()
