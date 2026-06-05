import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from reachly.models import GeneratedMedia, GeneratedPost, Platform, PlatformCredentials, PlatformMode
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

    def test_standalone_config_maps_x_oauth1_credentials(self):
        from reachly.config import AgentConfig

        cfg = AgentConfig(
            {
                "TWITTER_MODE": "api",
                "TWITTER_CONSUMER_KEY": "consumer-key",
                "TWITTER_CONSUMER_SECRET": "consumer-secret",
                "TWITTER_ACCESS_TOKEN": "access-token",
                "TWITTER_ACCESS_TOKEN_SECRET": "access-secret",
            }
        )

        creds = cfg.platforms[Platform.twitter]
        self.assertEqual(creds.extra["consumer_key"], "consumer-key")
        self.assertEqual(creds.extra["consumer_secret"], "consumer-secret")
        self.assertEqual(creds.extra["access_token"], "access-token")
        self.assertEqual(creds.extra["access_token_secret"], "access-secret")

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

    def test_saas_orchestrator_maps_x_oauth1_credentials(self):
        from server.orchestrator import _creds_from_secrets

        creds = _creds_from_secrets(
            Platform.twitter,
            PlatformMode.api,
            {
                "consumer_key": "consumer-key",
                "consumer_secret": "consumer-secret",
                "access_token": "access-token",
                "access_token_secret": "access-secret",
            },
        )

        self.assertEqual(creds.extra["consumer_key"], "consumer-key")
        self.assertEqual(creds.extra["consumer_secret"], "consumer-secret")
        self.assertEqual(creds.extra["access_token"], "access-token")
        self.assertEqual(creds.extra["access_token_secret"], "access-secret")

    def test_oauth1_header_is_used_when_token_pair_is_present(self):
        creds = PlatformCredentials(
            platform=Platform.twitter,
            mode=PlatformMode.api,
            extra={
                "consumer_key": "consumer-key",
                "consumer_secret": "consumer-secret",
                "access_token": "access-token",
                "access_token_secret": "access-secret",
            },
        )

        poster = TwitterApiPoster(creds)
        with patch("reachly.platforms.twitter.secrets.token_urlsafe", return_value="nonce"):
            with patch("reachly.platforms.twitter.time.time", return_value=1710000000):
                headers = poster._headers("POST", "https://api.x.com/2/tweets")

        auth = headers["Authorization"]
        self.assertTrue(auth.startswith("OAuth "))
        self.assertIn('oauth_consumer_key="consumer-key"', auth)
        self.assertIn('oauth_token="access-token"', auth)
        self.assertIn('oauth_signature_method="HMAC-SHA1"', auth)
        self.assertRegex(auth, re.compile(r'oauth_signature="[^"]+"'))

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

    def test_media_upload_payment_error_falls_back_to_text_only_tweet(self):
        calls = []

        class Response:
            def __init__(self, status_code, payload=None, text=""):
                self.status_code = status_code
                self._payload = payload or {}
                self.text = text

            def json(self):
                return self._payload

            def raise_for_status(self):
                if self.status_code >= 300:
                    error = requests.HTTPError(f"{self.status_code} error")
                    error.response = self
                    raise error

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/initialize"):
                return Response(200, {"data": {"id": "123"}})
            if url.endswith("/append"):
                return Response(402, text="Payment Required")
            if url.endswith("/tweets"):
                return Response(201, {"data": {"id": "tweet-123"}})
            return Response(200)

        creds = PlatformCredentials(
            platform=Platform.twitter,
            mode=PlatformMode.api,
            api_token="token",
        )
        post = GeneratedPost(
            theme="fashion catalog automation",
            hook="Catalog consistency used to be a luxury",
            body="Fashion teams can now create on-brand PDP and campaign visuals faster.",
            hashtags=["#fashiontech"],
            media=GeneratedMedia(kind="image", local_path=""),
        )
        poster = TwitterApiPoster(creds)
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "image.png"
            image.write_bytes(b"png")
            post.media.local_path = str(image)
            with patch("reachly.platforms.twitter.requests.post", side_effect=fake_post):
                result = poster.post(post)

        tweet_calls = [call for call in calls if call[0].endswith("/tweets")]
        self.assertTrue(result.ok)
        self.assertEqual(result.permalink, "https://x.com/i/web/status/tweet-123")
        self.assertEqual(len(tweet_calls), 1)
        self.assertNotIn("media", tweet_calls[0][1]["json"])


if __name__ == "__main__":
    unittest.main()
