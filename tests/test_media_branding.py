import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from reachly.agent import Agent, AgentSettings
from reachly.media import _apply_logo_overlay
from reachly.models import (
    BusinessProfile,
    GeneratedMedia,
    GeneratedPost,
    Platform,
    PlatformCredentials,
    PlatformMode,
)


class MediaBrandingTests(unittest.TestCase):
    def test_logo_overlay_marks_generated_image_corner(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "image.png"
            logo = Path(tmp) / "logo.png"
            Image.new("RGB", (300, 300), "white").save(image)
            Image.new("RGBA", (80, 80), (64, 64, 255, 255)).save(logo)

            _apply_logo_overlay(image, logo_path=str(logo), position="bottom-right", opacity=1)

            with Image.open(image).convert("RGB") as result:
                self.assertNotEqual(result.getpixel((260, 260)), (255, 255, 255))

    def test_white_logo_background_is_removed_before_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "image.png"
            logo = Path(tmp) / "logo.jpg"
            Image.new("RGB", (300, 300), (20, 30, 40)).save(image)
            logo_img = Image.new("RGB", (100, 100), "white")
            for x in range(30, 70):
                for y in range(30, 70):
                    logo_img.putpixel((x, y), (80, 70, 240))
            logo_img.save(logo, quality=95)

            _apply_logo_overlay(image, logo_path=str(logo), position="bottom-right", opacity=1)

            with Image.open(image).convert("RGB") as result:
                self.assertEqual(result.getpixel((232, 232)), (20, 30, 40))
                self.assertNotEqual(result.getpixel((256, 256)), (20, 30, 40))

    def test_text_platform_media_reuse_rate_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            post = GeneratedPost(
                theme="catalog ops",
                hook="A better PDP starts before the render",
                body="Body",
                media=GeneratedMedia(kind="image", local_path="/tmp/image.png"),
            )
            always = Agent(
                BusinessProfile(name="Hygaar"),
                {},
                AgentSettings(data_dir=tmp, text_platform_image_rate=1),
            )
            never = Agent(
                BusinessProfile(name="Hygaar"),
                {},
                AgentSettings(data_dir=tmp, text_platform_image_rate=0),
            )

            self.assertIsNotNone(always._post_for_platform(post, Platform.linkedin).media)
            self.assertIsNone(never._post_for_platform(post, Platform.twitter).media)
            self.assertIsNotNone(never._post_for_platform(post, Platform.instagram).media)
            always.close()
            never.close()

    def test_video_media_is_kept_for_linkedin_and_instagram_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            post = GeneratedPost(
                theme="catalog ops",
                hook="A better PDP starts before the render",
                body="Body",
                media=GeneratedMedia(kind="video", local_path="/tmp/video.mp4"),
            )
            agent = Agent(
                BusinessProfile(name="Hygaar"),
                {},
                AgentSettings(data_dir=tmp, text_platform_image_rate=0),
            )

            self.assertIsNotNone(agent._post_for_platform(post, Platform.linkedin).media)
            self.assertIsNotNone(agent._post_for_platform(post, Platform.instagram).media)
            self.assertIsNone(agent._post_for_platform(post, Platform.twitter).media)
            agent.close()

    def test_text_platform_image_rate_can_be_overridden_per_platform(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            post = GeneratedPost(
                theme="catalog ops",
                hook="A better PDP starts before the render",
                body="Body",
                media=GeneratedMedia(kind="image", local_path="/tmp/image.png"),
            )
            agent = Agent(
                BusinessProfile(name="Hygaar"),
                {},
                AgentSettings(
                    data_dir=tmp,
                    text_platform_image_rate=0,
                    linkedin_image_rate=1,
                ),
            )

            self.assertIsNotNone(agent._post_for_platform(post, Platform.linkedin).media)
            self.assertIsNone(agent._post_for_platform(post, Platform.twitter).media)
            agent.close()

    def test_linkedin_slot_uses_video_for_matching_media_plan_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            post = GeneratedPost(
                theme="catalog ops",
                hook="A better PDP starts before the render",
                body="Body",
                image_prompt="Premium ecommerce product media studio",
            )
            agent = Agent(
                BusinessProfile(name="Hygaar"),
                {
                    Platform.linkedin: PlatformCredentials(
                        platform=Platform.linkedin,
                        mode=PlatformMode.browser,
                    )
                },
                AgentSettings(
                    data_dir=tmp,
                    dry_run=True,
                    daily_media_plan=["image", "video"],
                    video_provider="seedance",
                    seedance_api_key="seedance-key",
                ),
            )

            def fake_video(p, **kwargs):
                p.media = GeneratedMedia(kind="video", local_path="/tmp/video.mp4")
                return p

            with patch.object(agent, "build_post", return_value=post):
                with patch.object(agent, "_ensure_video", side_effect=fake_video) as ensure_video:
                    results = agent.run_linkedin_slot(slot_index=1)

            self.assertTrue(results[Platform.linkedin].ok)
            self.assertEqual(ensure_video.call_count, 1)
            self.assertEqual(ensure_video.call_args.kwargs["strategy"], "recap")
            pending = agent._load_pending(max_age_minutes=60)
            self.assertEqual(pending.media.kind, "video")
            agent.close()

    def test_video_test_posts_only_linkedin_and_instagram(self):
        with tempfile.TemporaryDirectory() as tmp:
            post = GeneratedPost(
                theme="catalog ops",
                hook="Motion makes catalog quality obvious",
                body="Body",
                image_prompt="Premium ecommerce product video",
            )
            agent = Agent(
                BusinessProfile(name="Hygaar"),
                {
                    Platform.linkedin: PlatformCredentials(
                        platform=Platform.linkedin,
                        mode=PlatformMode.browser,
                    ),
                    Platform.instagram: PlatformCredentials(
                        platform=Platform.instagram,
                        mode=PlatformMode.browser,
                    ),
                    Platform.twitter: PlatformCredentials(
                        platform=Platform.twitter,
                        mode=PlatformMode.browser,
                    ),
                },
                AgentSettings(
                    data_dir=tmp,
                    dry_run=True,
                    video_provider="seedance",
                    seedance_api_key="seedance-key",
                ),
            )

            def fake_video(p, **kwargs):
                p.media = GeneratedMedia(kind="video", local_path="/tmp/video.mp4")
                return p

            with patch.object(agent, "build_post", return_value=post):
                with patch.object(agent, "_ensure_video", side_effect=fake_video):
                    results = agent.run_video_test()

            self.assertEqual(set(results), {Platform.linkedin, Platform.instagram})
            self.assertTrue(results[Platform.linkedin].ok)
            self.assertTrue(results[Platform.instagram].ok)
            pending = agent._load_pending(max_age_minutes=60)
            self.assertEqual(pending.media.kind, "video")
            agent.close()

    def test_second_daily_video_slot_uses_fresh_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            post = GeneratedPost(
                theme="catalog ops",
                hook="Fresh video ad",
                body="Body",
                image_prompt="Premium ecommerce product video",
            )
            agent = Agent(
                BusinessProfile(name="Hygaar"),
                {
                    Platform.linkedin: PlatformCredentials(
                        platform=Platform.linkedin,
                        mode=PlatformMode.browser,
                    )
                },
                AgentSettings(
                    data_dir=tmp,
                    dry_run=True,
                    daily_media_plan=["image", "image", "image", "video", "video"],
                    video_provider="seedance",
                    seedance_api_key="seedance-key",
                ),
            )

            def fake_video(p, **kwargs):
                p.media = GeneratedMedia(kind="video", local_path="/tmp/video.mp4")
                return p

            with patch.object(agent, "build_post", return_value=post):
                with patch.object(agent, "_ensure_video", side_effect=fake_video) as ensure_video:
                    results = agent.run_linkedin_slot(slot_index=4)

            self.assertTrue(results[Platform.linkedin].ok)
            self.assertEqual(ensure_video.call_args.kwargs["strategy"], "fresh")
            agent.close()

    def test_recap_video_context_uses_logo_and_recent_image_post_references(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            public_dir = tmp / "public"
            logo = tmp / "logo.png"
            logo.write_text("logo", encoding="utf-8")
            agent = Agent(
                BusinessProfile(name="Hygaar"),
                {},
                AgentSettings(
                    data_dir=tmp / "data",
                    brand_logo_path=str(logo),
                    public_media_base_url="https://reachly.example/media",
                    public_media_dir=public_dir,
                ),
            )
            for index in range(3):
                image = tmp / f"image-{index}.png"
                image.write_text(f"image {index}", encoding="utf-8")
                agent.history.record(
                    theme="catalog ops",
                    hook=f"Image post {index}",
                    body="Body",
                    platform="linkedin",
                    ok=True,
                    media_kind="image",
                    media_local_path=str(image),
                )
            post = GeneratedPost(theme="video", hook="Video hook", body="Body")

            creative = agent._build_video_creative_context(post, strategy="recap")

            self.assertEqual(creative.strategy, "recap")
            roles = [ref["role"] for ref in creative.reference_images]
            self.assertIn("brand_logo", roles)
            self.assertGreaterEqual(roles.count("previous_social_image"), 3)
            for ref in creative.reference_images:
                self.assertTrue(ref["url"].startswith("https://reachly.example/media/"))
            agent.close()

    def test_reference_from_path_uses_data_url_without_public_media(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            image = tmp / "reference.png"
            image.write_bytes(b"fake-image")
            agent = Agent(
                BusinessProfile(name="Hygaar"),
                {},
                AgentSettings(data_dir=tmp / "data"),
            )

            ref = agent._reference_from_path(str(image), role="previous_social_image")

            self.assertEqual(ref["role"], "previous_social_image")
            self.assertTrue(ref["url"].startswith("data:image/png;base64,"))
            agent.close()

    def test_forced_video_linkedin_does_not_publish_text_only_when_video_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            post = GeneratedPost(
                theme="catalog ops",
                hook="Motion makes catalog quality obvious",
                body="Body",
                image_prompt="Premium ecommerce product video",
            )
            agent = Agent(
                BusinessProfile(name="Hygaar"),
                {
                    Platform.linkedin: PlatformCredentials(
                        platform=Platform.linkedin,
                        mode=PlatformMode.browser,
                    )
                },
                AgentSettings(data_dir=tmp, dry_run=False, video_provider="none"),
            )

            with patch.object(agent, "build_post", return_value=post):
                with patch.object(agent, "_publish") as publish:
                    results = agent.run_once(platforms=[Platform.linkedin], media_kind="video")

            self.assertFalse(results[Platform.linkedin].ok)
            self.assertIn("Video generation did not produce", results[Platform.linkedin].error)
            publish.assert_not_called()
            agent.close()

    def test_forced_video_failure_surfaces_provider_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            post = GeneratedPost(
                theme="catalog ops",
                hook="Motion makes catalog quality obvious",
                body="Body",
                image_prompt="Premium ecommerce product video",
            )
            agent = Agent(
                BusinessProfile(name="Hygaar"),
                {
                    Platform.linkedin: PlatformCredentials(
                        platform=Platform.linkedin,
                        mode=PlatformMode.browser,
                    )
                },
                AgentSettings(data_dir=tmp, dry_run=False, video_provider="seedance"),
            )

            with patch.object(agent, "build_post", return_value=post):
                with patch.object(
                    agent,
                    "_generate_video",
                    side_effect=RuntimeError("AccountOverdueError: overdue balance"),
                ):
                    with patch.object(agent, "_publish") as publish:
                        results = agent.run_once(
                            platforms=[Platform.linkedin],
                            media_kind="video",
                        )

            self.assertFalse(results[Platform.linkedin].ok)
            self.assertIn("Provider error", results[Platform.linkedin].error)
            self.assertIn("AccountOverdueError", results[Platform.linkedin].error)
            publish.assert_not_called()
            agent.close()


if __name__ == "__main__":
    unittest.main()
