"""YouTube publishing via the official Data API resumable upload flow."""
from __future__ import annotations

import mimetypes
import time
from pathlib import Path

import requests

from ..models import GeneratedPost, Platform, PlatformCredentials, PostResult
from .base import Poster

UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK_SIZE = 8 * 1024 * 1024


class YouTubeApiPoster(Poster):
    platform = Platform.youtube

    def __init__(self, creds: PlatformCredentials):
        super().__init__(creds)

    def post(self, post: GeneratedPost) -> PostResult:
        if not post.media or post.media.kind != "video" or not post.media.local_path:
            return self._fail("YouTube API mode requires a generated video file.")
        path = Path(post.media.local_path)
        if not path.is_file():
            return self._fail(f"YouTube video file does not exist: {path}")
        try:
            access_token = self._access_token()
            video = self._upload_video(post, path, access_token=access_token)
            video_id = video.get("id")
            if not video_id:
                return self._fail(f"YouTube upload completed without a video id: {video}")
            return PostResult(
                platform=self.platform,
                ok=True,
                permalink=f"https://www.youtube.com/watch?v={video_id}",
            )
        except Exception as exc:  # noqa: BLE001
            return self._fail(str(exc))

    def _access_token(self) -> str:
        refresh_token = self.creds.extra.get("refresh_token") or ""
        client_id = self.creds.extra.get("client_id") or ""
        client_secret = self.creds.extra.get("client_secret") or ""
        if refresh_token and client_id and client_secret:
            token_uri = self.creds.extra.get("token_uri") or "https://oauth2.googleapis.com/token"
            resp = requests.post(
                token_uri,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=30,
            )
            if resp.status_code >= 300:
                raise RuntimeError(f"YouTube OAuth refresh failed ({resp.status_code}): {resp.text[:300]}")
            token = resp.json().get("access_token")
            if not token:
                raise RuntimeError("YouTube OAuth refresh response did not include access_token.")
            return token
        if self.creds.api_token:
            return self.creds.api_token
        raise RuntimeError(
            "YouTube API mode requires YOUTUBE_REFRESH_TOKEN with client credentials, "
            "or a valid YOUTUBE_ACCESS_TOKEN. Scope must be "
            f"{UPLOAD_SCOPE}."
        )

    def _upload_video(self, post: GeneratedPost, path: Path, *, access_token: str) -> dict:
        mime_type = mimetypes.guess_type(str(path))[0] or "video/mp4"
        total_size = path.stat().st_size
        if total_size <= 0:
            raise RuntimeError("YouTube upload file is empty.")
        params = {
            "uploadType": "resumable",
            "part": "snippet,status",
            "notifySubscribers": _bool_text(self.creds.extra.get("notify_subscribers", "false")),
        }
        body = {
            "snippet": {
                "title": _youtube_title(post.hook),
                "description": _youtube_description(post),
                "tags": _youtube_tags(post, self.creds.extra.get("default_tags", "")),
                "categoryId": self.creds.extra.get("category_id") or "22",
            },
            "status": {
                "privacyStatus": _privacy_status(self.creds.extra.get("privacy_status")),
                "containsSyntheticMedia": True,
            },
        }
        resp = requests.post(
            UPLOAD_URL,
            params=params,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(total_size),
                "X-Upload-Content-Type": mime_type,
            },
            json=body,
            timeout=60,
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"YouTube upload session failed ({resp.status_code}): {resp.text[:500]}")
        session_url = resp.headers.get("Location")
        if not session_url:
            raise RuntimeError("YouTube upload session response did not include Location header.")
        return _put_resumable_file(
            session_url,
            path,
            mime_type=mime_type,
            access_token=access_token,
            total_size=total_size,
        )


class YouTubeBrowserPoster(Poster):
    platform = Platform.youtube

    def post(self, post: GeneratedPost) -> PostResult:
        return self._fail("YouTube browser upload is not implemented; use API mode with OAuth.")


def _put_resumable_file(
    session_url: str,
    path: Path,
    *,
    mime_type: str,
    access_token: str,
    total_size: int,
) -> dict:
    offset = 0
    with open(path, "rb") as file_obj:
        while offset < total_size:
            file_obj.seek(offset)
            chunk = file_obj.read(min(CHUNK_SIZE, total_size - offset))
            if not chunk:
                break
            last_byte = offset + len(chunk) - 1
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Length": str(len(chunk)),
                "Content-Type": mime_type,
                "Content-Range": f"bytes {offset}-{last_byte}/{total_size}",
            }
            for retry in range(5):
                resp = requests.put(session_url, headers=headers, data=chunk, timeout=300)
                if resp.status_code in (200, 201):
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise RuntimeError(f"YouTube upload returned invalid JSON: {resp.text[:300]}") from exc
                if resp.status_code == 308:
                    offset = _next_offset(resp.headers.get("Range"), fallback=last_byte + 1)
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        time.sleep(min(60, int(retry_after)))
                    break
                if resp.status_code in (500, 502, 503, 504):
                    time.sleep(min(60, 2**retry))
                    continue
                if resp.status_code == 404:
                    raise RuntimeError("YouTube resumable upload session expired; start a new upload.")
                raise RuntimeError(f"YouTube upload failed ({resp.status_code}): {resp.text[:500]}")
            else:
                raise RuntimeError("YouTube upload failed after retries.")
            if offset <= last_byte and resp.status_code == 308:
                offset = last_byte + 1
    raise RuntimeError("YouTube upload did not complete.")


def _next_offset(range_header: str | None, *, fallback: int) -> int:
    if not range_header or "=" not in range_header or "-" not in range_header:
        return fallback
    try:
        return int(range_header.rsplit("-", 1)[1]) + 1
    except ValueError:
        return fallback


def _youtube_title(value: str) -> str:
    title = " ".join((value or "Hygaar video").split())
    return title[:100].rstrip()


def _youtube_description(post: GeneratedPost) -> str:
    text = post.body.strip()
    if post.link and post.link not in text:
        text = f"{text}\n\n{post.link}".strip()
    tags = " ".join(post.hashtags)
    if tags and tags not in text:
        text = f"{text}\n\n{tags}".strip()
    return text[:5000]


def _youtube_tags(post: GeneratedPost, defaults: str) -> list[str]:
    raw_values = [*post.hashtags, *defaults.replace(",", " ").split()]
    tags: list[str] = []
    for raw in raw_values:
        tag = raw.strip().lstrip("#")
        if not tag:
            continue
        if tag.lower() not in {item.lower() for item in tags}:
            tags.append(tag[:30])
        if len(tags) >= 15:
            break
    return tags


def _privacy_status(value: str | None) -> str:
    cleaned = (value or "private").strip().lower()
    return cleaned if cleaned in {"private", "unlisted", "public"} else "private"


def _bool_text(value: str | None) -> str:
    return "true" if str(value or "").strip().lower() in {"1", "true", "yes", "on"} else "false"
