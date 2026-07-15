from reachly.config import AgentConfig
from reachly.content import generate_medium_article
from reachly.models import BusinessProfile, GeneratedPost, Platform, PlatformMode
from reachly.platforms import get_poster
from reachly.platforms.medium import MediumBrowserPoster, _article_parts, _paragraphs
from reachly.runner import _parse_times


class FakeLLM:
    def __init__(self):
        self.prompt = ""

    def generate_json(self, system_prompt, user_prompt):
        self.prompt = user_prompt
        return {
            "theme": "catalog trust",
            "title": "Your Catalogue Is Quietly Deciding Whether Customers Trust You",
            "subtitle": "The image grid is now commercial infrastructure.",
            "body": "Catalogue consistency is no longer a design detail.\n\nIt is a growth constraint.",
            "tags": ["Ecommerce", "#Marketing", "Catalog Management", "AI"],
            "image_prompt": "A premium ecommerce catalogue production table with fashion products",
            "cta_link": None,
        }


def test_medium_config_maps_three_daily_slots_and_browser_mode():
    cfg = AgentConfig(
        {
            "MEDIUM_MODE": "browser",
            "MEDIUM_TIMES": "09:30,14:30,19:30",
            "MEDIUM_PUBLISH_STATUS": "public",
            "MEDIUM_EXPECTED_ACCOUNT": "Rohit Sharma",
        }
    )

    creds = cfg.platforms[Platform.medium]
    assert creds.mode == PlatformMode.browser
    assert creds.extra["publish_status"] == "public"
    assert creds.extra["expected_account"] == "Rohit Sharma"
    assert _parse_times(cfg.medium_times_raw) == ["09:30", "14:30", "19:30"]
    assert cfg.medium_image_aspect_ratio == "16:9"


def test_generate_medium_article_targets_leaders_and_16x9_images():
    llm = FakeLLM()
    article = generate_medium_article(
        llm,
        BusinessProfile(
            name="Hygaar",
            website="https://hygaar.com",
            sector="AI product media",
            product_info="AI product images for ecommerce catalogues",
        ),
        theme="catalog trust",
        performance_context="- medium | catalogue trust | high engagement",
        newness_context="medium last 1 posts:\n  - old hook",
    )

    assert "CEOs" in llm.prompt
    assert "catalogue heads" in llm.prompt
    assert "850-1300 words" in llm.prompt
    assert "AI product photography" in llm.prompt
    assert "AI photoshoots for products" in llm.prompt
    assert "bulk generation of SKU images" in llm.prompt
    assert article.hook == "Your Catalogue Is Quietly Deciding Whether Customers Trust You"
    assert article.body.startswith("The image grid is now commercial infrastructure.")
    assert article.hashtags == ["Ecommerce", "Marketing", "Catalog Management", "AI"]
    assert "16:9 horizontal" in article.image_prompt


def test_medium_factory_returns_browser_poster(tmp_path):
    cfg = AgentConfig({"MEDIUM_MODE": "browser"})
    poster = get_poster(cfg.platforms[Platform.medium], data_dir=tmp_path)

    assert isinstance(poster, MediumBrowserPoster)


def test_medium_paragraph_split_ignores_empty_blocks():
    assert _paragraphs("A\n\n\nB\n\n ") == ["A", "B"]


def test_medium_article_parts_keep_title_out_of_body():
    title, paragraphs = _article_parts(
        GeneratedPost(
            theme="catalogue",
            hook="AI Product Photography Is Catalogue Infrastructure",
            body="Subtitle goes here.\n\nFirst body paragraph.",
        )
    )

    assert title == "AI Product Photography Is Catalogue Infrastructure"
    assert paragraphs == ["Subtitle goes here.", "First body paragraph."]
