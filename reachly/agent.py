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

import base64
import json
import hashlib
import logging
import mimetypes
import re
import shutil
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import AgentConfig
from .content import generate_engagement_comment, generate_medium_article, generate_post, pick_theme
from .context import load_strategy_context
from .llm import LLMClient
from .media import (
    HygaarClient,
    SeedanceClient,
    add_openai_voiceover,
    generate_image_gemini,
    video_has_audio,
)
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
    video_provider: str = "none"          # seedance | hygaar | none
    hygaar_base_url: Optional[str] = None
    hygaar_api_token: Optional[str] = None
    seedance_api_key: Optional[str] = None
    seedance_base_url: str = "https://ark.ap-southeast.bytepluses.com/api/v3"
    seedance_model: str = "seedance_2_5"
    seedance_fallback_model: str = "seedance_2_0"
    seedance_ratio: str = "9:16"
    seedance_target_duration: int = 30
    seedance_clip_count: int = 2
    seedance_clip_duration: int = 15
    seedance_generate_audio: bool = True
    seedance_watermark: bool = False
    video_voiceover_enabled: bool = True
    video_voiceover_provider: str = "openai"
    video_voiceover_model: str = "tts-1"
    video_voiceover_voice: str = "alloy"
    daily_media_plan: list[str] = field(default_factory=list)
    brand_logo_path: Optional[str] = None
    brand_logo_position: str = "bottom-right"

    attach_image: bool = True
    dry_run: bool = True
    data_dir: Path = field(default_factory=lambda: Path("./.reachly_data"))
    public_media_base_url: Optional[str] = None
    public_media_dir: Optional[Path] = None
    context_repo: Optional[str] = None
    agents_md_path: Optional[str] = None
    product_theory_path: Optional[str] = None
    posting_style: str = "thought_leader"
    enable_engagement: bool = False
    engagement_delay_minutes: int = 30
    engagement_max_comments: int = 3
    text_platform_image_rate: float = 0.5
    linkedin_image_rate: Optional[float] = None
    twitter_image_rate: Optional[float] = None
    medium_image_aspect_ratio: str = "16:9"
    video_generated_reference_count: int = 3


@dataclass
class VideoCreativeContext:
    strategy: str = "fresh"
    reference_images: list[dict[str, str]] = field(default_factory=list)
    source_posts: list[dict] = field(default_factory=list)


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
        self._last_video_error: Optional[str] = None
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
            seedance_api_key=cfg.seedance_api_key,
            seedance_base_url=cfg.seedance_base_url,
            seedance_model=cfg.seedance_model,
            seedance_fallback_model=cfg.seedance_fallback_model,
            seedance_ratio=cfg.seedance_ratio,
            seedance_target_duration=cfg.seedance_target_duration,
            seedance_clip_count=cfg.seedance_clip_count,
            seedance_clip_duration=cfg.seedance_clip_duration,
            seedance_generate_audio=cfg.seedance_generate_audio,
            seedance_watermark=cfg.seedance_watermark,
            video_voiceover_enabled=cfg.video_voiceover_enabled,
            video_voiceover_provider=cfg.video_voiceover_provider,
            video_voiceover_model=cfg.video_voiceover_model,
            video_voiceover_voice=cfg.video_voiceover_voice,
            daily_media_plan=cfg.daily_media_plan,
            brand_logo_path=cfg.brand_logo_path,
            brand_logo_position=cfg.brand_logo_position,
            attach_image=cfg.attach_image,
            dry_run=cfg.dry_run,
            data_dir=cfg.data_dir,
            public_media_base_url=cfg.public_media_base_url,
            public_media_dir=Path(cfg.public_media_dir) if cfg.public_media_dir else None,
            context_repo=repo,
            agents_md_path=cfg.agents_md_path,
            product_theory_path=cfg.product_theory_path,
            posting_style=style,
            enable_engagement=cfg.enable_engagement,
            engagement_delay_minutes=cfg.engagement_delay_minutes,
            engagement_max_comments=cfg.engagement_max_comments,
            text_platform_image_rate=cfg.text_platform_image_rate,
            linkedin_image_rate=cfg.linkedin_image_rate,
            twitter_image_rate=cfg.twitter_image_rate,
            medium_image_aspect_ratio=cfg.medium_image_aspect_ratio,
        )
        return cls(cfg.business, cfg.platforms, settings)

    # ------------------------------------------------------------------
    def build_post(
        self,
        theme: Optional[str] = None,
        *,
        attach_image: Optional[bool] = None,
    ) -> GeneratedPost:
        theme = theme or self._select_theme()
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
        should_attach_image = self.settings.attach_image if attach_image is None else attach_image
        if should_attach_image and post.image_prompt:
            try:
                post.media = self._generate_media(post.image_prompt)
            except Exception as e:  # noqa: BLE001
                logger.warning("Media generation failed (%s); posting text-only.", e)
        return post

    def _select_theme(self) -> str:
        themes = self.business.themes_or_default()
        if not themes:
            return pick_theme(self.business)
        recent = {
            theme.strip().lower()
            for theme in self.history.recent_themes(limit=max(1, min(len(themes) - 1, 5)))
        }
        start = date.today().toordinal() % len(themes)
        for offset in range(len(themes)):
            candidate = themes[(start + offset) % len(themes)]
            if candidate.strip().lower() not in recent:
                return candidate
        return pick_theme(self.business)

    def build_medium_article(self, theme: Optional[str] = None) -> GeneratedPost:
        theme = theme or self._select_theme()
        logger.info("Generating Medium article for theme: %s", theme)
        post = generate_medium_article(
            self.llm,
            self.business,
            theme=theme,
            recent_hooks=self.history.recent_hooks(),
            performance_context=self.history.analytics_summary(days=14, limit=12),
            newness_context=self.history.newness_summary(limit_per_platform=3),
            strategy=self._strategy,
        )
        return self._ensure_image(post, aspect_ratio=self.settings.medium_image_aspect_ratio)

    def _generate_media(self, prompt: str, *, aspect_ratio: str = "1:1") -> Optional[GeneratedMedia]:
        media_dir = self.settings.data_dir / "media"
        if self.settings.image_provider == "gemini":
            media = generate_image_gemini(
                prompt,
                api_key=self.settings.gemini_api_key,
                model=self.settings.gemini_image_model,
                out_dir=media_dir,
                logo_path=self.settings.brand_logo_path,
                logo_position=self.settings.brand_logo_position,
                aspect_ratio=aspect_ratio,
            )
            return self._make_public_media(media)
        if self.settings.image_provider == "hygaar":
            client = HygaarClient(self.settings.hygaar_base_url, self.settings.hygaar_api_token)
            media = client.generate_image(
                prompt,
                media_dir,
                logo_path=self.settings.brand_logo_path,
                logo_position=self.settings.brand_logo_position,
            )
            return self._make_public_media(media)
        return None

    def _make_public_media(self, media: Optional[GeneratedMedia]) -> Optional[GeneratedMedia]:
        if not media:
            return None
        if media.public_url:
            return media
        if not (self.settings.public_media_base_url and self.settings.public_media_dir):
            return media
        source = Path(media.local_path).expanduser()
        if not source.is_file():
            return media
        public_dir = Path(self.settings.public_media_dir)
        public_dir.mkdir(parents=True, exist_ok=True)
        target = public_dir / source.name
        try:
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            media.local_path = str(target)
            media.public_url = f"{self.settings.public_media_base_url.rstrip('/')}/{target.name}"
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not publish media reference %s (%s).", source, e)
        return media

    def _reference_from_path(self, path: str, *, role: str = "reference_image") -> Optional[dict[str, str]]:
        media = self._make_public_media(
            GeneratedMedia(kind="image", local_path=path, mime_type="image/png")
        )
        if media and media.public_url:
            return {"url": media.public_url, "role": role}
        source = Path(path).expanduser()
        if not source.is_file() or source.stat().st_size > 8_000_000:
            return None
        mime_type = mimetypes.guess_type(str(source))[0] or "image/png"
        if not mime_type.startswith("image/"):
            return None
        try:
            encoded = base64.b64encode(source.read_bytes()).decode("ascii")
        except OSError:
            return None
        return {"url": f"data:{mime_type};base64,{encoded}", "role": role}

    def _brand_reference_images(self) -> list[dict[str, str]]:
        if not self.settings.brand_logo_path:
            return []
        logo = Path(self.settings.brand_logo_path).expanduser()
        if not logo.is_file():
            return []
        ref = self._reference_from_path(str(logo), role="brand_logo")
        return [ref] if ref else []

    def _recent_image_file_references(self, *, limit: int = 3) -> list[dict[str, str]]:
        media_dir = self.settings.data_dir / "media"
        if not media_dir.is_dir():
            return []
        files = [
            path
            for path in media_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        refs = []
        for path in files[:limit]:
            ref = self._reference_from_path(str(path), role="previous_social_image")
            if ref:
                refs.append(ref)
        return refs

    def _recent_image_post_references(self, *, limit: int = 3) -> tuple[list[dict[str, str]], list[dict]]:
        refs: list[dict[str, str]] = []
        posts: list[dict] = []
        seen_urls: set[str] = set()
        seen_hooks: set[str] = set()
        for row in self.history.recent_image_posts(limit=limit * 3):
            hook_key = (row.get("hook") or "").strip().lower()
            if hook_key and hook_key in seen_hooks:
                continue
            ref = None
            if row.get("media_public_url"):
                ref = {"url": row["media_public_url"], "role": "previous_social_image"}
            elif row.get("media_local_path"):
                ref = self._reference_from_path(row["media_local_path"], role="previous_social_image")
            if not ref or ref["url"] in seen_urls:
                continue
            seen_urls.add(ref["url"])
            if hook_key:
                seen_hooks.add(hook_key)
            refs.append(ref)
            posts.append(row)
            if len(refs) >= limit:
                break
        if len(refs) < limit:
            for ref in self._recent_image_file_references(limit=limit - len(refs)):
                if ref["url"] not in seen_urls:
                    refs.append(ref)
                    seen_urls.add(ref["url"])
        return refs, posts

    def _fresh_video_reference_images(self, post: GeneratedPost, *, count: int = 3) -> list[dict[str, str]]:
        prompts = [
            (
                "Create a vertical premium ecommerce reference still for a Hygaar ad: "
                "a messy SKU/catalog workflow transforms into an organized AI media command center. "
                "No readable text, no fake dashboards, high-end studio lighting."
            ),
            (
                "Create a vertical reference still showing product catalog scale: many product variants, "
                "consistent lighting, clean ecommerce composition, premium but operational. No text."
            ),
            (
                "Create a vertical reference still for the closing shot of a genAI catalog content ad: "
                "polished product media outputs ready for marketplace, PDP, ads, and social. No text."
            ),
        ]
        refs: list[dict[str, str]] = []
        for index, base_prompt in enumerate(prompts[: max(1, count)], start=1):
            prompt = (
                f"{base_prompt}\nBrand: {self.business.name}. "
                f"Post context: {post.hook} {post.body[:500]}. "
                f"Reference frame {index}; keep visual continuity with the other frames."
            )
            try:
                media = self._generate_media(prompt, aspect_ratio="9:16")
            except Exception as e:  # noqa: BLE001
                logger.warning("Fresh video reference image generation failed (%s).", e)
                continue
            if media and media.public_url:
                refs.append({"url": media.public_url, "role": "generated_storyboard_image"})
        return refs

    def _build_video_creative_context(
        self,
        post: GeneratedPost,
        *,
        strategy: str = "auto",
    ) -> VideoCreativeContext:
        base_refs = self._brand_reference_images()
        if strategy in ("auto", "recap"):
            recent_refs, source_posts = self._recent_image_post_references(limit=3)
            if strategy == "recap" or recent_refs:
                refs = base_refs + recent_refs
                if len(recent_refs) < 2:
                    refs += self._fresh_video_reference_images(
                        post,
                        count=max(1, 2 - len(recent_refs)),
                    )
                return VideoCreativeContext(
                    strategy="recap",
                    reference_images=refs,
                    source_posts=source_posts,
                )

        fresh_refs = self._fresh_video_reference_images(
            post,
            count=self.settings.video_generated_reference_count,
        )
        return VideoCreativeContext(
            strategy="fresh",
            reference_images=base_refs + fresh_refs,
            source_posts=[],
        )

    def _generate_video(
        self,
        prompt: str,
        *,
        reference_images: Optional[list[dict[str, str]]] = None,
    ) -> Optional[GeneratedMedia]:
        media_dir = self.settings.data_dir / "media"
        if self.settings.video_provider == "seedance":
            client = SeedanceClient(
                self.settings.seedance_api_key,
                base_url=self.settings.seedance_base_url,
                model_key=self.settings.seedance_model,
                fallback_model_key=self.settings.seedance_fallback_model,
            )
            media = client.generate_video(
                prompt,
                media_dir,
                ratio=self.settings.seedance_ratio,
                target_duration=self.settings.seedance_target_duration,
                clip_count=self.settings.seedance_clip_count,
                clip_duration=self.settings.seedance_clip_duration,
                generate_audio=self.settings.seedance_generate_audio,
                watermark=self.settings.seedance_watermark,
                reference_images=reference_images,
            )
            return self._make_public_media(media)
        if self.settings.video_provider == "hygaar":
            client = HygaarClient(self.settings.hygaar_base_url, self.settings.hygaar_api_token)
            media = client.generate_video(prompt, media_dir)
            return self._make_public_media(media)
        return None

    def _video_prompt_for_post(
        self,
        post: GeneratedPost,
        creative: VideoCreativeContext,
    ) -> str:
        hashtags = " ".join(post.hashtags[:4])
        source_prompt = post.image_prompt or post.hook
        source_posts = "\n".join(
            f"- {row.get('theme')}: {row.get('hook')} {str(row.get('body') or '')[:260]}"
            for row in creative.source_posts[:3]
        )
        if creative.strategy == "recap":
            strategy_direction = (
                "Use the reference images and recent post themes as a coherent daily recap ad. "
                "Turn the last image-post ideas into one narrative: catalog chaos, AI production "
                "system, consistent SKU-ready output, and business impact."
            )
        else:
            strategy_direction = (
                "Create a fresh conversion-oriented ad concept that positions Hygaar as the "
                "catalog content at scale genAI layer for ecommerce teams."
            )
        return (
            f"Create a premium {self.settings.seedance_target_duration}-second vertical social video "
            f"for {self.business.name}.\n"
            f"Business: {self.business.sector or 'AI-powered product media'}.\n"
            f"Product context: {self.business.product_info or self.business.vision or post.body[:400]}.\n"
            f"Post hook: {post.hook}\n"
            f"Post body context: {post.body[:900]}\n"
            f"Visual direction: {source_prompt}\n"
            f"Creative strategy: {creative.strategy}. {strategy_direction}\n"
            f"Recent image-post source material:\n{source_posts or 'No prior image-post text available.'}\n"
            "Voiceover/script direction: speak to ecommerce operators who need catalogue images, "
            "variant visuals, PDP content, marketplace assets, and ad creatives at scale. Make the "
            "message concrete: fewer manual shoots, consistent brand quality, faster SKU launches, "
            "and AI agents that handle production workflows.\n"
            f"Hashtag context: {hashtags}\n\n"
            "Requirements: cinematic ecommerce/product-media quality, strong opening motion in the "
            "first two seconds, multi-angle and multi-scene storytelling inside one coherent ad, "
            "realistic lighting, no fake UI, no fake logos, no readable on-screen text, no watermark, "
            "no distorted products, clean ending frame suitable for Instagram Reels and LinkedIn feed."
        )

    def _ensure_video(self, post: GeneratedPost, *, strategy: str = "auto") -> GeneratedPost:
        if post.media and post.media.kind == "video" and post.media.local_path:
            return post
        self._last_video_error = None
        creative = self._build_video_creative_context(post, strategy=strategy)
        prompt = self._video_prompt_for_post(post, creative)
        try:
            post.media = self._generate_video(prompt, reference_images=creative.reference_images)
            post.media = self._add_video_voiceover_if_needed(post, post.media)
        except Exception as e:  # noqa: BLE001
            self._last_video_error = str(e)
            logger.warning("Video generation failed (%s).", e)
        return post

    def _add_video_voiceover_if_needed(
        self,
        post: GeneratedPost,
        media: GeneratedMedia,
    ) -> GeneratedMedia:
        if not self.settings.video_voiceover_enabled:
            return media
        if self.settings.video_voiceover_provider != "openai":
            return media
        video_path = Path(media.local_path)
        if not video_path.is_file():
            return media
        try:
            if video_has_audio(video_path):
                return media
            if not self.settings.openai_api_key:
                logger.warning(
                    "Generated video is silent and OPENAI_API_KEY is not set; using original video."
                )
                return media
            script = self._video_voiceover_script(post)
            voiced = add_openai_voiceover(
                media,
                script,
                api_key=self.settings.openai_api_key,
                out_dir=self.settings.data_dir / "media",
                model=self.settings.video_voiceover_model,
                voice=self.settings.video_voiceover_voice,
            )
            logger.info("Added voiceover to generated video: %s", voiced.local_path)
            return voiced
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not add video voiceover; using original silent video (%s).", e)
            return media

    def _video_voiceover_script(self, post: GeneratedPost, *, max_words: int = 78) -> str:
        hook = post.hook.strip().rstrip(".")
        body = post.body.strip()
        if body.lower().startswith(hook.lower()):
            text = body
        else:
            text = f"{hook}. {body}"
        text = re.sub(r"https?://\\S+", "", text)
        text = re.sub(r"#\\w+", "", text)
        text = re.sub(r"\\s+", " ", text).strip()
        words = text.split()
        if len(words) > max_words:
            text = " ".join(words[:max_words]).rstrip(".,;:") + "."
        return text or hook or self.business.name

    def _has_video(self, post: GeneratedPost) -> bool:
        return bool(post.media and post.media.kind == "video" and post.media.local_path)

    def _video_required_results(self, platforms: list[Platform]) -> dict[Platform, PostResult]:
        error = "Video generation did not produce a video; no post was published."
        if self._last_video_error:
            error = f"{error} Provider error: {self._last_video_error[:500]}"
        return {
            platform: PostResult(platform=platform, ok=False, error=error)
            for platform in platforms
        }

    # ------------------------------------------------------------------
    def _pending_path(self) -> Path:
        return self.settings.data_dir / "pending_instagram_post.json"

    def _engagement_pending_path(self) -> Path:
        return self.settings.data_dir / "pending_linkedin_engagement.json"

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

    def schedule_linkedin_engagement(self, run_at: datetime, post: Optional[GeneratedPost] = None) -> None:
        post = post or self._last_linkedin_post or self._load_pending(max_age_minutes=240)
        if not post:
            logger.info("Engagement follow-up not scheduled: no LinkedIn post snapshot.")
            return
        payload = post.model_dump(mode="json")
        payload["_run_at"] = run_at.isoformat()
        payload["_saved_at"] = datetime.utcnow().isoformat()
        tmp = self._engagement_pending_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self._engagement_pending_path())
        logger.info("Persisted LinkedIn engagement follow-up for %s.", run_at.isoformat())

    def run_due_engagement(self, now: Optional[datetime] = None) -> int:
        path = self._engagement_pending_path()
        if not path.is_file():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            run_at = datetime.fromisoformat(data.pop("_run_at"))
            data.pop("_saved_at", None)
            current = now or (datetime.now(run_at.tzinfo) if run_at.tzinfo else datetime.utcnow())
            if current < run_at:
                return 0
            self._last_linkedin_post = GeneratedPost.model_validate(data)
            count = self.engage_after_linkedin_post()
            path.unlink(missing_ok=True)
            return count
        except Exception:
            logger.exception("LinkedIn engagement follow-up failed.")
            return 0

    def _ensure_image(self, post: GeneratedPost, *, aspect_ratio: str = "1:1") -> GeneratedPost:
        if post.media and post.media.local_path:
            return post
        if not self.settings.attach_image:
            return post
        if not post.image_prompt:
            post.image_prompt = f"Professional social media image illustrating: {post.hook}"
        try:
            post.media = self._generate_media(post.image_prompt, aspect_ratio=aspect_ratio)
        except Exception as e:  # noqa: BLE001
            logger.warning("Image generation failed (%s).", e)
        return post

    def _media_kind_for_slot(
        self,
        *,
        slot_index: Optional[int] = None,
        media_kind: Optional[str] = None,
    ) -> str:
        if media_kind and media_kind != "auto":
            return media_kind if media_kind in ("image", "video") else "image"
        plan = [item for item in self.settings.daily_media_plan if item in ("image", "video")]
        if plan and slot_index is not None:
            return plan[slot_index % len(plan)]
        return "image"

    def _video_strategy_for_slot(
        self,
        *,
        slot_index: Optional[int] = None,
        strategy: Optional[str] = None,
    ) -> str:
        if strategy and strategy != "auto":
            return strategy if strategy in ("recap", "fresh") else "fresh"
        plan = [item for item in self.settings.daily_media_plan if item in ("image", "video")]
        if plan and slot_index is not None:
            video_number = sum(1 for item in plan[: (slot_index % len(plan)) + 1] if item == "video")
            return "recap" if video_number == 1 else "fresh"
        return "auto"

    def run_linkedin_slot(
        self,
        theme: Optional[str] = None,
        *,
        slot_index: Optional[int] = None,
        media_kind: Optional[str] = None,
        video_strategy: Optional[str] = None,
    ) -> dict[Platform, PostResult]:
        """Generate content, queue for Instagram, post primary text platforms."""
        with self._run_lock:
            kind = self._media_kind_for_slot(slot_index=slot_index, media_kind=media_kind)
            post = self.build_post(theme, attach_image=(kind == "image" and self.settings.attach_image))
            if kind == "video":
                strategy = self._video_strategy_for_slot(
                    slot_index=slot_index,
                    strategy=video_strategy,
                )
                post = self._ensure_video(post, strategy=strategy)
                if not self._has_video(post):
                    return self._video_required_results([Platform.linkedin, Platform.twitter])
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
            if not (post.media and post.media.kind == "video"):
                post = self._ensure_image(post)
            if not post.media:
                return {
                    Platform.instagram: PostResult(
                        platform=Platform.instagram,
                        ok=False,
                        error="Instagram requires generated image or video media.",
                    )
                }
            return self._publish(post, platforms=[Platform.instagram])

    def run_medium_slot(self, theme: Optional[str] = None) -> dict[Platform, PostResult]:
        """Generate and publish one long-form Medium article with a 16:9 image."""
        with self._run_lock:
            post = self.build_medium_article(theme)
            if not post.media:
                return {
                    Platform.medium: PostResult(
                        platform=Platform.medium,
                        ok=False,
                        error="Medium article requires a 16:9 image; generation failed.",
                    )
                }
            return self._publish(post, platforms=[Platform.medium])

    def run_once(
        self,
        theme: Optional[str] = None,
        *,
        platforms: Optional[list[Platform]] = None,
        media_kind: Optional[str] = None,
        video_strategy: Optional[str] = None,
    ) -> dict[Platform, PostResult]:
        with self._run_lock:
            kind = self._media_kind_for_slot(media_kind=media_kind)
            post = self.build_post(theme, attach_image=(kind == "image" and self.settings.attach_image))
            if kind == "video":
                post = self._ensure_video(
                    post,
                    strategy=self._video_strategy_for_slot(strategy=video_strategy),
                )
                if not self._has_video(post):
                    target_platforms = platforms or [p for p, c in self.platforms.items() if c.enabled]
                    return self._video_required_results(target_platforms)
            if kind != "video" and (platforms is None or Platform.instagram in platforms):
                post = self._ensure_image(post)
            if platforms is None or Platform.linkedin in platforms:
                self._save_pending(post)
            results = self._publish(post, platforms=platforms)
            if results.get(Platform.linkedin) and results[Platform.linkedin].ok:
                self._last_linkedin_post = post
            return results

    def run_video_test(
        self,
        theme: Optional[str] = None,
        *,
        video_strategy: Optional[str] = None,
    ) -> dict[Platform, PostResult]:
        """Generate one video and publish only to LinkedIn + Instagram."""
        with self._run_lock:
            post = self.build_post(theme, attach_image=False)
            post = self._ensure_video(
                post,
                strategy=self._video_strategy_for_slot(strategy=video_strategy),
            )
            if not self._has_video(post):
                return self._video_required_results([Platform.linkedin, Platform.instagram])
            self._save_pending(post)
            results = self._publish(post, platforms=[Platform.linkedin, Platform.instagram])
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
            publish_post = self._post_for_platform(post, platform)
            result = poster.post(publish_post)
            results[platform] = result
            media = publish_post.media
            self.history.record(
                theme=post.theme,
                hook=post.hook,
                body=post.body,
                platform=platform.value,
                ok=result.ok,
                permalink=result.permalink,
                error=result.error,
                media_kind=media.kind if media else None,
                media_local_path=media.local_path if media else None,
                media_public_url=media.public_url if media else None,
                media_prompt=media.prompt if media else None,
                post_text=publish_post.for_platform(platform),
            )
            if result.ok:
                logger.info("✓ %s posted: %s", platform.value, result.permalink or "(ok)")
            else:
                logger.error("✗ %s failed: %s", platform.value, result.error)

        return results

    def _post_for_platform(self, post: GeneratedPost, platform: Platform) -> GeneratedPost:
        if platform in (Platform.instagram, Platform.medium) or not post.media:
            return post
        if post.media.kind == "video":
            return post if platform == Platform.linkedin else post.model_copy(update={"media": None})
        if self._use_media_on_text_platform(post, platform):
            return post
        return post.model_copy(update={"media": None})

    def _use_media_on_text_platform(self, post: GeneratedPost, platform: Platform) -> bool:
        configured_rate = self.settings.text_platform_image_rate
        if platform == Platform.linkedin and self.settings.linkedin_image_rate is not None:
            configured_rate = self.settings.linkedin_image_rate
        elif platform == Platform.twitter and self.settings.twitter_image_rate is not None:
            configured_rate = self.settings.twitter_image_rate
        rate = max(0.0, min(1.0, configured_rate))
        if rate >= 1:
            return True
        if rate <= 0:
            return False
        key = f"{post.theme}|{post.hook}".encode("utf-8")
        bucket = int(hashlib.sha256(key).hexdigest()[:8], 16) % 100
        return bucket < int(rate * 100)

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
