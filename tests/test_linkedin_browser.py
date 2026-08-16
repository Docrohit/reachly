from reachly.models import Platform, PlatformCredentials, PlatformMode
from reachly.platforms.linkedin import LinkedInBrowserPoster, _normalize_text, _text_probe


def test_linkedin_text_probe_is_stable_across_whitespace():
    text = "First line\n\nSecond   line\twith spacing"

    assert _normalize_text(text) == "First line Second line with spacing"
    assert _text_probe(text) == "First line Second line with spacing"


class FakeLocator:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout=None):
        return self.text


class FakePage:
    def __init__(self, text):
        self.text = text
        self.waits = 0

    def wait_for_timeout(self, ms):
        self.waits += 1

    def locator(self, selector):
        assert selector == "body"
        return FakeLocator(self.text)


def test_linkedin_video_post_verification_accepts_success_signal(tmp_path):
    poster = LinkedInBrowserPoster(
        PlatformCredentials(platform=Platform.linkedin, mode=PlatformMode.browser),
        data_dir=tmp_path,
    )

    assert poster._verify_post_submitted(
        FakePage("Your post is live. View post"),
        "A video about Hygaar quality control",
        "video",
    )


def test_linkedin_video_post_verification_rejects_blocking_error(tmp_path):
    poster = LinkedInBrowserPoster(
        PlatformCredentials(platform=Platform.linkedin, mode=PlatformMode.browser),
        data_dir=tmp_path,
    )

    assert not poster._verify_post_submitted(
        FakePage("Something went wrong. Please try again."),
        "A video about Hygaar quality control",
        "video",
    )
