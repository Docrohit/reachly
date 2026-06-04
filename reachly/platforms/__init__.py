"""Platform posting adapters (API mode + headless browser mode)."""
from __future__ import annotations

from ..models import GeneratedPost, Platform, PlatformCredentials, PlatformMode, PostResult
from .base import Poster


def get_poster(creds: PlatformCredentials, *, data_dir, public_media_base_url=None) -> Poster:
    """Factory: return the right poster for a platform + mode."""
    if creds.platform == Platform.twitter:
        if creds.mode == PlatformMode.api:
            from .twitter import TwitterApiPoster

            return TwitterApiPoster(creds)
        from .twitter import TwitterBrowserPoster

        return TwitterBrowserPoster(creds, data_dir=data_dir)

    if creds.platform == Platform.linkedin:
        if creds.mode == PlatformMode.api:
            from .linkedin import LinkedInApiPoster

            return LinkedInApiPoster(creds)
        from .linkedin import LinkedInBrowserPoster

        return LinkedInBrowserPoster(creds, data_dir=data_dir)

    if creds.platform == Platform.instagram:
        if creds.mode == PlatformMode.api:
            from .instagram import InstagramApiPoster

            return InstagramApiPoster(creds, public_media_base_url=public_media_base_url)
        from .instagram import InstagramBrowserPoster

        return InstagramBrowserPoster(creds, data_dir=data_dir)

    raise ValueError(f"Unsupported platform: {creds.platform}")


__all__ = ["get_poster", "Poster"]
