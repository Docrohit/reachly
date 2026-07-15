"""Hygaar account authentication bridge.

Reachly is deployed as a separate app, but Hygaar-acquired deployments should
let existing Hygaar console users sign in with their normal email/password. This
module only calls the Hygaar auth API and returns sanitized account data for the
Reachly server to map into its own local user table.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

import requests

from .settings import get_settings


@dataclass
class HygaarLoginResult:
    access_token: str
    refresh_token: str
    user: dict


class HygaarAuthError(Exception):
    """Raised when Hygaar rejects login or the auth API is unavailable."""


def login_with_hygaar(email: str, password: str) -> HygaarLoginResult:
    settings = get_settings()
    login_url = urljoin(f"{settings.hygaar_api_base_url}/", settings.hygaar_login_path.lstrip("/"))
    try:
        response = requests.post(
            login_url,
            json={"email": email.strip().lower(), "password": password},
            timeout=settings.hygaar_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise HygaarAuthError("Could not reach Hygaar login. Please try again.") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise HygaarAuthError("Hygaar login returned an invalid response.") from exc

    if response.status_code >= 400 or payload.get("status") != "success":
        raise HygaarAuthError(payload.get("message") or "Invalid Hygaar credentials.")

    data = payload.get("data") or {}
    user = data.get("user") or {}
    access = data.get("access_token") or ""
    refresh = data.get("refresh_token") or ""
    if not access or not user.get("user_id"):
        raise HygaarAuthError("Hygaar login did not return a usable account.")

    return HygaarLoginResult(access_token=access, refresh_token=refresh, user=user)
