from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from reachly.models import GeneratedMedia, GeneratedPost, Platform, PlatformCredentials, PlatformMode
from reachly.platforms.linkedin import LinkedInApiPoster


def test_linkedin_api_uses_organization_author_when_configured():
    creds = PlatformCredentials(
        platform=Platform.linkedin,
        mode=PlatformMode.api,
        api_token="token",
        extra={"organization_id": "123456"},
    )

    poster = LinkedInApiPoster(creds)

    with patch("reachly.platforms.linkedin.requests.get") as get:
        assert poster._resolve_author() == "urn:li:organization:123456"

    get.assert_not_called()


def test_linkedin_api_accepts_organization_urn():
    creds = PlatformCredentials(
        platform=Platform.linkedin,
        mode=PlatformMode.api,
        api_token="token",
        extra={"organization_id": "urn:li:organization:123456"},
    )

    assert LinkedInApiPoster(creds)._resolve_author() == "urn:li:organization:123456"


def test_linkedin_api_uploads_video_and_attaches_video_urn():
    calls = []

    class Response:
        def __init__(self, payload=None, status_code=200, headers=None, text=""):
            self._payload = payload or {}
            self.status_code = status_code
            self.headers = headers or {}
            self.text = text

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 300:
                raise RuntimeError(self.text or f"{self.status_code} error")

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        if url.endswith("/videos?action=initializeUpload"):
            return Response(
                {
                    "value": {
                        "video": "urn:li:video:C4E10AQF",
                        "uploadToken": "upload-token",
                        "uploadInstructions": [
                            {
                                "firstByte": 0,
                                "lastByte": 3,
                                "uploadUrl": "https://upload.linkedin.example/video",
                            }
                        ],
                    }
                }
            )
        if url.endswith("/videos?action=finalizeUpload"):
            return Response({})
        if url.endswith("/posts"):
            return Response({}, status_code=201, headers={"x-restli-id": "urn:li:share:123"})
        raise AssertionError(url)

    def fake_put(url, **kwargs):
        calls.append(("put", url, kwargs))
        assert kwargs["data"] == b"vid1"
        return Response({}, headers={"ETag": '"part-1"'})

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        return Response({"status": "AVAILABLE"})

    creds = PlatformCredentials(
        platform=Platform.linkedin,
        mode=PlatformMode.api,
        api_token="token",
        extra={"organization_id": "123456"},
    )
    post = GeneratedPost(
        theme="catalog ops",
        hook="Catalog motion now matters",
        body="AI product media teams need more than static images.",
        media=GeneratedMedia(kind="video", local_path=""),
    )

    with TemporaryDirectory() as tmp:
        video = Path(tmp) / "video.mp4"
        video.write_bytes(b"vid1")
        post.media.local_path = str(video)
        with patch("reachly.platforms.linkedin.requests.post", side_effect=fake_post):
            with patch("reachly.platforms.linkedin.requests.put", side_effect=fake_put):
                with patch("reachly.platforms.linkedin.requests.get", side_effect=fake_get):
                    result = LinkedInApiPoster(creds).post(post)

    assert result.ok
    finalize = [call for call in calls if call[1].endswith("/videos?action=finalizeUpload")][0]
    finalize_request = finalize[2]["json"]["finalizeUploadRequest"]
    assert finalize_request["video"] == "urn:li:video:C4E10AQF"
    assert finalize_request["uploadToken"] == "upload-token"
    assert finalize_request["uploadedPartIds"] == ["part-1"]
    post_call = [call for call in calls if call[1].endswith("/posts")][0]
    assert post_call[2]["json"]["content"]["media"]["id"] == "urn:li:video:C4E10AQF"
