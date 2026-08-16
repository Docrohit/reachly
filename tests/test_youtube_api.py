from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from reachly.models import GeneratedMedia, GeneratedPost, Platform, PlatformCredentials, PlatformMode
from reachly.platforms.youtube import UPLOAD_SCOPE, YouTubeApiPoster


class Response:
    def __init__(self, payload=None, status_code=200, headers=None, text=""):
        self._payload = payload or {}
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


def test_youtube_oauth_refresh_uses_upload_scope_credentials():
    creds = PlatformCredentials(
        platform=Platform.youtube,
        mode=PlatformMode.api,
        extra={
            "refresh_token": "refresh",
            "client_id": "client",
            "client_secret": "secret",
        },
    )
    poster = YouTubeApiPoster(creds)

    with patch(
        "reachly.platforms.youtube.requests.post",
        return_value=Response({"access_token": "fresh-access-token"}),
    ) as post:
        token = poster._access_token()

    assert token == "fresh-access-token"
    assert post.call_args.kwargs["data"]["grant_type"] == "refresh_token"
    assert post.call_args.kwargs["data"]["refresh_token"] == "refresh"
    assert UPLOAD_SCOPE == "https://www.googleapis.com/auth/youtube.upload"


def test_youtube_upload_uses_resumable_video_insert_metadata():
    calls = []

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return Response(status_code=200, headers={"Location": "https://upload.youtube.example/session"})

    def fake_put(url, **kwargs):
        calls.append(("put", url, kwargs))
        return Response({"id": "abc123"}, status_code=201)

    creds = PlatformCredentials(
        platform=Platform.youtube,
        mode=PlatformMode.api,
        api_token="token",
        extra={
            "privacy_status": "unlisted",
            "category_id": "28",
            "notify_subscribers": "false",
            "default_tags": "Hygaar, AI Product Media",
        },
    )
    post = GeneratedPost(
        theme="moat",
        hook="Why Hygaar beats building video in-house",
        body="Narration-led product education.",
        hashtags=["#Hygaar", "#EcommerceAI"],
        media=GeneratedMedia(kind="video", local_path=""),
    )

    with TemporaryDirectory() as tmp:
        video = Path(tmp) / "video.mp4"
        video.write_bytes(b"vid1")
        post.media.local_path = str(video)
        with patch("reachly.platforms.youtube.requests.post", side_effect=fake_post):
            with patch("reachly.platforms.youtube.requests.put", side_effect=fake_put):
                result = YouTubeApiPoster(creds).post(post)

    assert result.ok
    assert result.permalink == "https://www.youtube.com/watch?v=abc123"
    session = calls[0][2]
    assert session["params"]["uploadType"] == "resumable"
    assert session["params"]["part"] == "snippet,status"
    assert session["json"]["status"]["privacyStatus"] == "unlisted"
    assert session["json"]["status"]["selfDeclaredMadeForKids"] is False
    assert session["json"]["status"]["containsSyntheticMedia"] is True
    assert session["json"]["snippet"]["categoryId"] == "28"
    assert "Hygaar" in session["json"]["snippet"]["tags"]
    put = calls[1][2]
    assert put["headers"]["Content-Range"] == "bytes 0-3/4"
    assert put["data"] == b"vid1"
