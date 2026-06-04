"""Base poster interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models import GeneratedPost, Platform, PlatformCredentials, PostResult


class Poster(ABC):
    platform: Platform

    def __init__(self, creds: PlatformCredentials):
        self.creds = creds

    @abstractmethod
    def post(self, post: GeneratedPost) -> PostResult:
        """Publish the post and return a result."""

    # convenience
    def _ok(self, permalink: Optional[str] = None) -> PostResult:
        return PostResult(platform=self.platform, ok=True, permalink=permalink)

    def _fail(self, error: str) -> PostResult:
        return PostResult(platform=self.platform, ok=False, error=error)
