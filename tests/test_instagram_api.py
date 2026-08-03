from unittest.mock import patch

from reachly.models import GeneratedMedia, GeneratedPost, Platform, PlatformCredentials, PlatformMode
from reachly.platforms.instagram import InstagramApiPoster, InstagramBrowserPoster


class Response:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload or {}
        self.status_code = status_code
        self.text = text

    @property
    def ok(self):
        return self.status_code < 300

    def json(self):
        return self._payload


def test_instagram_api_posts_video_as_reels_container():
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/ig-user/media"):
            return Response({"id": "creation-1"})
        if url.endswith("/ig-user/media_publish"):
            return Response({"id": "ig-post-1"})
        raise AssertionError(url)

    creds = PlatformCredentials(
        platform=Platform.instagram,
        mode=PlatformMode.api,
        api_token="token",
        extra={"user_id": "ig-user"},
    )
    post = GeneratedPost(
        theme="catalog ops",
        hook="Motion sells the product before copy does",
        body="AI product media needs video for the feed.",
        media=GeneratedMedia(
            kind="video",
            local_path="/tmp/video.mp4",
            public_url="https://cdn.example/final-video.mp4",
            mime_type="video/mp4",
        ),
    )

    with patch("reachly.platforms.instagram.requests.post", side_effect=fake_post):
        with patch(
            "reachly.platforms.instagram.requests.get",
            return_value=Response({"status_code": "FINISHED"}),
        ):
            result = InstagramApiPoster(creds).post(post)

    assert result.ok
    create_payload = calls[0][1]["data"]
    assert create_payload["media_type"] == "REELS"
    assert create_payload["video_url"] == "https://cdn.example/final-video.mp4"
    assert create_payload["share_to_feed"] == "true"
    assert "image_url" not in create_payload


def test_instagram_browser_uses_post_create_url_for_video(tmp_path):
    creds = PlatformCredentials(platform=Platform.instagram, mode=PlatformMode.browser)

    poster = InstagramBrowserPoster(creds, data_dir=tmp_path)

    assert poster._create_urls("video")[0] == "https://www.instagram.com/create/select/"
    assert poster._create_urls("image")[0] == "https://www.instagram.com/create/select/"
