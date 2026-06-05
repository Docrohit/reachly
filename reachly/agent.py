"""The agent harness.

Given a BusinessProfile + platform credentials + provider settings, the agent:
  1. picks today's theme,
  2. generates a post (LLM),
  3. optionally generates an image (Gemini / Hygaar),
  4. posts to every enabled platform (API or browser),
  5. records the result.

It works identically whether driven by the standalone .env config or by the
SaaS server (which builds the same inputs from its database).
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import AgentConfig
from .content import generate_engagement_comment, generate_post, pick_theme
from .context import load_strategy_context
from .llm import LLMClient
from .media import HygaarClient, generate_image_gemini
from .models import (
    BusinessProfile,
    GeneratedMedia,
    GeneratedPost,
    Platform,
    PlatformCredentials,
    PostResult,
)
from .platforms import get_poster
from .storage import History

logger = logging.getLogger("reachly.agent")


@dataclass
class AgentSettings:
    llm_provider: str = "gemini"
    llm_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    image_provider: str = "none"          # gemini | hygaar | none
    gemini_image_model: str = "gemini-2.5-flash-image"
    video_provider: str = "none"          # hygaar | none
    hygaar_base_url: Optional[str] = None
    hygaar_api_token: Optional[str] = None

    attach_image: bool = True
    dry_run: bool = True
    data_dir: Path = field(default_factory=lambda: Path("./.reachly_data"))
    public_media_base_url: Optional[str] = None
    context_repo: Optional[str] = None
    agents_md_path: Optional[str] = None
    product_theory_path: Optional[str] = None
    posting_style: str = "thought_leader"
    enable_engagement: bool = False
    engagement_delay_minutes: int = 30
    engagement_max_comments: int = 3


class Agent:
    def __init__(
        self,
        business: BusinessProfile,
        platforms: dict[Platform, PlatformCredentials],
        settings: AgentSettings,
    ):
        self.business = business
        self.platforms = platforms
        self.settings = settings
        self.settings.data_dir = Path(settings.data_dir)
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.history = History(self.settings.data_dir)
        self._run_lock = threading.RLock()

        self.llm = LLMClient(
            settings.llm_provider,
            model=settings.llm_model,
            gemini_api_key=settings.gemini_api_key,
            openai_api_key=settings.openai_api_key,
            anthropic_api_key=settings.anthropic_api_key,
        )
        self._strategy = load_strategy_context(
            data_dir=self.settings.data_dir,
            context_repo=settings.context_repo,
            agents_path=settings.agents_md_path,
            product_theory_path=settings.product_theory_path,
            posting_style=settings.posting_style,
        )
        self._last_linkedin_post: Optional[GeneratedPost] = None
        logger.info("Strategy context source: %s", self._strategy.source)

    @classmethod
    def from_config(cls, cfg: "AgentConfig") -> "Agent":
        from .settings_store import load_dashboard_settings

        dash = load_dashboard_settings(cfg.data_dir)
        style = dash.get("posting_style") or cfg.posting_style
        repo = dash.get("context_repo") or cfg.context_repo

        settings = AgentSettings(
            llm_provider=cfg.llm_provider,
            llm_model=cfg.llm_model,
            gemini_api_key=cfg.gemini_api_key,
            openai_api_key=cfg.openai_api_key,
            anthropic_api_key=cfg.anthropic_api_key,
            image_provider=cfg.image_provider,
            gemini_image_model=cfg.gemini_image_model,
            video_provider=cfg.video_provider,
            hygaar_base_url=cfg.hygaar_base_url,
            hygaar_api_token=cfg.hygaar_api_token,
            attach_image=cfg.attach_image,
            dry_run=cfg.dry_run,
            data_dir=cfg.data_dir,
            public_media_base_url=cfg.public_media_base_url,
            context_repo=repo,
            agents_md_path=cfg.agents_md_path,
            product_theory_path=cfg.product_theory_path,
            posting_style=style,
            enable_engagement=cfg.enable_engagement,
            engagement_delay_minutes=cfg.engagement_delay_minutes,
            engagement_max_comments=cfg.engagement_max_comments,
        )
        return cls(cfg.business, cfg.platforms, settings)

    # ------------------------------------------------------------------
    def build_post(self, theme: Optional[str] = None) -> GeneratedPost:
        theme = theme or pick_theme(self.business)
        logger.info("Generating post for theme: %s", theme)
        post = generate_post(
            self.llm,
            self.business,
            theme=theme,
            recent_hooks=self.history.recent_hooks(),
            performance_context=self.history.analytics_summary(days=14, limit=12),
            newness_context=self.history.newness_summary(limit_per_platform=3),
            strategy=self._strategy,
        )
        if self.settings.attach_image and post.image_prompt:
            try:
                post.media = self._generate_media(post.image_prompt)
            except Exception as e:  # noqa: BLE001
                logger.warning("Media generation failed (%s); posting text-only.", e)
        return post

    def _generate_media(self, prompt: str) -> Optional[GeneratedMedia]:
        media_dir = self.settings.data_dir / "media"
        if self.settings.image_provider == "gemini":
            return generate_image_gemini(
                prompt,
                api_key=self.settings.gemini_api_key,
                model=self.settings.gemini_image_model,
                out_dir=media_dir,
            )
        if self.settings.image_provider == "hygaar":
            client = HygaarClient(self.settings.hygaar_base_url, self.settings.hygaar_api_token)
            return client.generate_image(prompt, media_dir)
        return None

    # ------------------------------------------------------------------
    def _pending_path(self) -> Path:
        return self.settings.data_dir / "pending_instagram_post.json"

    def _save_pending(self, post: GeneratedPost) -> None:
        payload = post.model_dump(mode="json")
        payload["_saved_at"] = datetime.utcnow().isoformat()
        tmp = self._pending_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self._pending_path())

    def _load_pending(self, max_age_minutes: int = 30) -> Optional[GeneratedPost]:
        path = self._pending_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            saved = datetime.fromisoformat(data.pop("_saved_at", ""))
            if datetime.utcnow() - saved > timedelta(minutes=max_age_minutes):
                return None
            return GeneratedPost.model_validate(data)
        except Exception:  # noqa: BLE001
            return None

    def _ensure_image(self, post: GeneratedPost) -> GeneratedPost:
        if post.media and post.media.local_path:
            return post
        if not self.settings.attach_image:
            return post
        if not post.image_prompt:
            post.image_prompt = f"Professional social media image illustrating: {post.hook}"
        try:
            post.media = self._generate_media(post.image_prompt)
        except Exception as e:  # noqa: BLE001
            logger.warning("Image generation failed (%s).", e)
        return post

    def run_linkedin_slot(self, theme: Optional[str] = None) -> dict[Platform, PostResult]:
        """Generate content, queue for Instagram, post primary text platforms."""
        with self._run_lock:
            post = self.build_post(theme)
            self._save_pending(post)
            results = self._publish(post, platforms=[Platform.linkedin, Platform.twitter])
            if results.get(Platform.linkedin) and results[Platform.linkedin].ok:
                self._last_linkedin_post = post
            return results

    def run_instagram_slot(self) -> dict[Platform, PostResult]:
        """Post to Instagram using pending LinkedIn content + generated image."""
        with self._run_lock:
            post = self._load_pending()
            if not post:
                logger.info("No pending post; generating fresh content for Instagram.")
                post = self.build_post()
            post = self._ensure_image(post)
            if not post.media:
                return {
                    Platform.instagram: PostResult(
                        platform=Platform.instagram,
                        ok=False,
                        error="Instagram requires an image; generation failed.",
                    )
                }
            return self._publish(post, platforms=[Platform.instagram])

    def run_once(
        self,
        theme: Optional[str] = None,
        *,
        platforms: Optional[list[Platform]] = None,
    ) -> dict[Platform, PostResult]:
        with self._run_lock:
            post = self.build_post(theme)
            if platforms is None or Platform.instagram in platforms:
                post = self._ensure_image(post)
            if platforms is None or Platform.linkedin in platforms:
                self._save_pending(post)
            results = self._publish(post, platforms=platforms)
            if results.get(Platform.linkedin) and results[Platform.linkedin].ok:
                self._last_linkedin_post = post
            return results

    def _publish(
        self,
        post: GeneratedPost,
        *,
        platforms: Optional[list[Platform]] = None,
    ) -> dict[Platform, PostResult]:
        print("\n" + "=" * 70)
        print(f"THEME : {post.theme}")
        print(f"HOOK  : {post.hook}")
        print(f"BODY  : {post.body}")
        print(f"TAGS  : {' '.join(post.hashtags)}")
        print(f"LINK  : {post.link}")
        if post.media:
            print(f"MEDIA : {post.media.local_path}")
        print("=" * 70 + "\n")

        results: dict[Platform, PostResult] = {}
        for platform, creds in self.platforms.items():
            if platforms is not None and platform not in platforms:
                continue
            if not creds.enabled:
                continue
            if self.settings.dry_run:
                logger.info("[DRY RUN] Would post to %s (%s mode).", platform.value, creds.mode.value)
                print(f"--- {platform.value.upper()} ({creds.mode.value}) ---")
                print(post.for_platform(platform))
                print()
                results[platform] = PostResult(platform=platform, ok=True, permalink="(dry-run)")
                continue

            poster = get_poster(
                creds,
                data_dir=self.settings.data_dir,
                public_media_base_url=self.settings.public_media_base_url,
            )
            logger.info("Posting to %s (%s) ...", platform.value, creds.mode.value)
            result = poster.post(post)
            results[platform] = result
            self.history.record(
                theme=post.theme,
                hook=post.hook,
                body=post.body,
                platform=platform.value,
                ok=result.ok,
                permalink=result.permalink,
                error=result.error,
            )
            if result.ok:
                logger.info("✓ %s posted: %s", platform.value, result.permalink or "(ok)")
            else:
                logger.error("✗ %s failed: %s", platform.value, result.error)

        return results

    def analytics_review(self) -> str:
        """Return the recent performance context used by the writer."""
        review = self.history.analytics_summary(days=14, limit=24)
        newness = self.history.newness_summary(limit_per_platform=3)
        if newness:
            return review + "\n\nRecent posts to avoid repeating:\n" + newness
        return review

    def engage_after_linkedin_post(self) -> int:
        """Find relevant hashtag conversations and leave a few genuine comments."""
        post = self._last_linkedin_post or self._load_pending(max_age_minutes=240)
        if not post:
            logger.info("Engagement skipped: no recent LinkedIn post found.")
            return 0
        creds = self.platforms.get(Platform.linkedin)
        if not creds or not creds.enabled:
            logger.info("Engagement skipped: LinkedIn is disabled.")
            return 0
        poster = get_poster(
            creds,
            data_dir=self.settings.data_dir,
            public_media_base_url=self.settings.public_media_base_url,
        )
        if not hasattr(poster, "engage_with_hashtags"):
            logger.info("Engagement skipped: LinkedIn API engagement is not implemented.")
            return 0

        def _make_comment(hashtag: str, source_text: str) -> str:
            return generate_engagement_comment(
                self.llm,
                self.business,
                hashtag=hashtag,
                source_post_text=source_text,
            )

        return poster.engage_with_hashtags(
            post.hashtags,
            make_comment=_make_comment,
            max_comments=self.settings.engagement_max_comments,
        )

    def close(self) -> None:
        self.history.close()
