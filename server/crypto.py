"""Credential vault: symmetric encryption for stored platform secrets.

Secrets (passwords, OAuth tokens, API keys) are encrypted at rest with Fernet
using REACHLY_VAULT_KEY. They are only decrypted in-memory when an agent run
needs them.
"""
from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet

from .settings import get_settings


def _fernet() -> Fernet:
    key = get_settings().vault_key
    if not key:
        raise RuntimeError(
            "REACHLY_VAULT_KEY is not set. Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_dict(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return _fernet().encrypt(raw).decode()


def decrypt_dict(token: str) -> dict[str, Any]:
    if not token:
        return {}
    raw = _fernet().decrypt(token.encode())
    return json.loads(raw.decode())
