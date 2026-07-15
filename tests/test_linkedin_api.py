from unittest.mock import patch

from reachly.models import Platform, PlatformCredentials, PlatformMode
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
