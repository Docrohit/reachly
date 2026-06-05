import tempfile
import unittest
from pathlib import Path

from PIL import Image

from reachly.agent import Agent, AgentSettings
from reachly.media import _apply_logo_overlay
from reachly.models import BusinessProfile, GeneratedMedia, GeneratedPost, Platform


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


if __name__ == "__main__":
    unittest.main()
