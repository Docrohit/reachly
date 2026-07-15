"""Production preflight checks for hosted Reachly.

Run with:
    python -m server.preflight
    python -m server.preflight --hygaar-auth

The optional Hygaar auth check reads credentials from environment variables and
never prints passwords, access tokens, or refresh tokens.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping

from cryptography.fernet import Fernet

from .hygaar_auth import HygaarAuthError, login_with_hygaar
from .settings import ServerSettings

AUTH_EMAIL_ENV = "REACHLY_PREFLIGHT_HYGAAR_EMAIL"
AUTH_PASSWORD_ENV = "REACHLY_PREFLIGHT_HYGAAR_PASSWORD"


def validate_settings(settings: ServerSettings) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if settings.production:
        if not settings.public_base_url.startswith("https://"):
            errors.append("REACHLY_PUBLIC_BASE_URL must be https:// in production.")
        if not settings.hygaar_api_base_url.startswith("https://"):
            errors.append("REACHLY_HYGAAR_API_BASE_URL must be https:// in production.")
        if settings.database_url.startswith("sqlite:///./"):
            warnings.append(
                "REACHLY_DATABASE_URL uses a relative SQLite path; prefer an absolute "
                "server path or managed database for production."
            )
        if settings.telegram_login_enabled:
            warnings.append(
                "REACHLY_TELEGRAM_LOGIN_ENABLED is true; Hygaar login should be the "
                "primary hosted auth path."
            )

    try:
        if settings.vault_key:
            Fernet(settings.vault_key.encode())
    except Exception:  # noqa: BLE001
        errors.append("REACHLY_VAULT_KEY is not a valid Fernet key.")

    return errors, warnings


def run_hygaar_auth_check(env: Mapping[str, str] | None = None) -> tuple[bool, str]:
    env = env or os.environ
    email = (env.get(AUTH_EMAIL_ENV) or "").strip()
    password = env.get(AUTH_PASSWORD_ENV) or ""
    if not email or not password:
        return (
            False,
            f"Set {AUTH_EMAIL_ENV} and {AUTH_PASSWORD_ENV} to run the Hygaar auth check.",
        )

    try:
        result = login_with_hygaar(email, password)
    except HygaarAuthError as exc:
        return False, f"Hygaar auth failed: {exc}"

    user = result.user or {}
    user_id = user.get("user_id") or "unknown"
    user_email = user.get("email") or email
    return True, f"Hygaar auth ok for {user_email} ({user_id})."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run hosted Reachly preflight checks.")
    parser.add_argument(
        "--hygaar-auth",
        action="store_true",
        help=(
            "Also verify Hygaar auth using REACHLY_PREFLIGHT_HYGAAR_EMAIL and "
            "REACHLY_PREFLIGHT_HYGAAR_PASSWORD."
        ),
    )
    args = parser.parse_args(argv)

    try:
        settings = ServerSettings()
    except RuntimeError as exc:
        print(f"settings: error: {exc}", file=sys.stderr)
        return 1

    errors, warnings = validate_settings(settings)
    for warning in warnings:
        print(f"settings: warning: {warning}")
    if errors:
        for error in errors:
            print(f"settings: error: {error}", file=sys.stderr)
        return 1
    print("settings: ok")

    if args.hygaar_auth:
        ok, message = run_hygaar_auth_check()
        stream = sys.stdout if ok else sys.stderr
        print(message, file=stream)
        if not ok:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
