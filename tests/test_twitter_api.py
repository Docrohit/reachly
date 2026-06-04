import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reachly.models import Platform, PlatformCredentials, PlatformMode
from reachly.platforms.twitter import TwitterApiPoster


class TwitterApiTests(unittest.TestCase):
    def test_standalone_config_maps_x_login_identifier(self):
        from reachly.config import AgentConfig

        cfg = AgentConfig(
            {
                "TWITTER_MODE": "browser",
                "TWITTER_USERNAME": "hygaar",
                "TWITTER_PASSWORD": "secret",
                "TWITTER_LOGIN_IDENTIFIER": "rohitsharma@hygaar.com",
            }
        )

        creds = cfg.platforms[Platform.twitter]
        self.assertEqual(creds.extra["login_identifier"], "rohitsharma@hygaar.com")

    def test_saas_orchestrator_maps_x_login_identifier(self):
        from server.orchestrator import _creds_from_secrets

        creds = _creds_from_secrets(
            Platform.twitter,
            PlatformMode.browser,
            {
                "username": "hygaar",
                "password": "secret",
                "login_identifier": "rohitsharma@hygaar.com",
            },
        )

        self.assertEqual(creds.extra["login_identifier"], "rohitsharma@hygaar.com")

    def test_image_upload_uses_current_v2_media_endpoints(self):
        calls = []

        class Response:
            status_code = 200

            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/initialize"):
                return Response({"data": {"id": "123", "processing_info": {"state": "succeeded"}}})
            return Response({"data": {"id": "123"}})

        creds = PlatformCredentials(
            platform=Platform.twitter,
            mode=PlatformMode.api,
            api_token="token",
        )
        poster = TwitterApiPoster(creds)
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "image.png"
            image.write_bytes(b"png")
            with patch("reachly.platforms.twitter.requests.post", side_effect=fake_post):
                media_id = poster._upload_image(str(image))

        self.assertEqual(media_id, "123")
        self.assertEqual(calls[0][0], "https://api.x.com/2/media/upload/initialize")
        self.assertEqual(calls[0][1]["json"]["media_category"], "tweet_image")
        self.assertEqual(calls[1][0], "https://api.x.com/2/media/upload/123/append")
        self.assertEqual(calls[2][0], "https://api.x.com/2/media/upload/123/finalize")


if __name__ == "__main__":
    unittest.main()
