"""One approved payload per invocation, JSON stdin/stdout; no autonomous generation.

REACHLY_CLINIC_BINDINGS is an operator-owned JSON mapping connection UUIDs to
{clinic_id, platform, account, page_url}. Cookies are isolated by connection UUID
under REACHLY_CLINIC_DATA. Media must already exist under REACHLY_CLINIC_MEDIA.
Never point these variables at the standalone Hygaar browser profiles.
"""
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
from pathlib import Path
from uuid import UUID
from contextlib import contextmanager
import fcntl
from .models import GeneratedPost, GeneratedMedia, Platform, PlatformCredentials, PlatformMode
from .platforms import get_poster

logger = logging.getLogger(__name__)


@contextmanager
def profile_lock(path):
    with path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def publish(payload, *, bindings, data_root, media_root):
    request_id = str(UUID(payload["request_id"]))
    connection_id = str(UUID(payload["connection_id"]))
    binding = bindings.get(connection_id, {})
    if binding.get("clinic_id") != payload["clinic_id"] or binding.get("platform") != payload["platform"]:
        raise ValueError("Clinic connection mismatch")
    if payload.get("account") != binding.get("account"):
        raise ValueError("Approved account binding changed")
    platform = Platform(binding["platform"])
    if platform not in (Platform.instagram, Platform.facebook):
        raise ValueError("Unsupported clinic publishing channel")
    account = binding.get("account", "")
    if not account or (platform == Platform.instagram and not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", account)):
        raise ValueError("Missing or invalid account binding")
    caption = payload["caption"]
    if not isinstance(caption, str) or not caption.strip() or len(caption) > 2200:
        raise ValueError("Caption must contain 1 to 2200 characters")
    media_root = Path(media_root).resolve()
    media = (media_root / payload["media_name"]).resolve()
    if not media.is_relative_to(media_root) or not media.is_file():
        raise ValueError("Media is unavailable")
    if hashlib.sha256(media.read_bytes()).hexdigest() != payload["media_sha256"]:
        raise ValueError("Approved media has changed")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    root = Path(data_root) / connection_id
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with profile_lock(root / "publish.lock"):
        with sqlite3.connect(root / "receipts.sqlite3") as db:
            db.execute("CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, digest TEXT, result TEXT)")
            old = db.execute("SELECT digest, result FROM receipts WHERE id=?", (request_id,)).fetchone()
            if old:
                if old[0] != digest:
                    raise ValueError("Idempotency payload mismatch")
                return json.loads(old[1])
            pending = {"status": "needs_attention", "message": "Publishing outcome unknown; review the account before any new attempt."}
            db.execute("INSERT INTO receipts VALUES (?, ?, ?)", (request_id, digest, json.dumps(pending)))
            db.commit()  # Durable before browser side effects, including process termination.
            creds = PlatformCredentials(platform=platform, mode=PlatformMode.browser,
                extra={"expected_account": account, "page_url": binding.get("page_url", "")})
            # Empty hook/tags/link means the exact approved caption is used, without rewriting.
            post = GeneratedPost(theme="Approved clinic post", hook="", body=caption,
                media=GeneratedMedia(kind="image", local_path=str(media)))
            result = get_poster(creds, data_dir=root).post(post)
            receipt = {"status": "published" if result.ok else "needs_attention",
                "permalink": result.permalink or "", "confirmed_at": result.posted_at.isoformat() if result.ok else None,
                "message": "Browser confirmed publication." if result.ok else "Review browser session and publication outcome.",
                "evidence": "platform_confirmation" if result.ok else "unconfirmed"}
            db.execute("UPDATE receipts SET result=? WHERE id=?", (json.dumps(receipt), request_id))
            db.commit()
            return receipt


def main():
    try:
        raw = sys.stdin.read(8_000_001)
        if len(raw) > 8_000_000:
            raise ValueError("Payload too large")
        payload = json.loads(raw)
        bindings = json.loads(Path(os.environ["REACHLY_CLINIC_BINDINGS"]).read_text())
        result = publish(payload, bindings=bindings, data_root=os.environ["REACHLY_CLINIC_DATA"],
                         media_root=os.environ["REACHLY_CLINIC_MEDIA"])
    except Exception as exc:
        # Preserve the JSON contract and avoid replay after any uncertain browser side effect.
        logger.warning("Clinic browser handoff unconfirmed: %s", type(exc).__name__)
        result = {"status": "needs_attention", "message": "Browser handoff could not be confirmed. Check connection configuration and journal."}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
