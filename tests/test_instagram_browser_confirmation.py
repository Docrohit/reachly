from pathlib import Path
from unittest.mock import MagicMock, patch
from reachly.models import GeneratedPost, GeneratedMedia, Platform, PlatformCredentials, PlatformMode
from reachly.platforms.instagram import InstagramBrowserPoster


@patch("reachly.platforms.instagram.persistent_page")
def test_instagram_share_without_confirmation_is_not_success(context):
    page = context.return_value.__enter__.return_value
    poster = InstagramBrowserPoster(PlatformCredentials(platform=Platform.instagram, mode=PlatformMode.browser), data_dir=Path("/unused"))
    poster._needs_login = MagicMock(return_value=False)
    poster._open_create = MagicMock(return_value=True)
    poster._upload_media = MagicMock(return_value=True)
    poster._caption_box = MagicMock()
    poster._caption_box.return_value.count.return_value = 1
    page.get_by_text.return_value.first.wait_for.side_effect = TimeoutError("No platform confirmation")
    post = GeneratedPost(theme="demo", hook="", body="Approved", media=GeneratedMedia(kind="image", local_path="/unused.png"))
    assert not poster.post(post).ok
    page.get_by_text.assert_called_once_with("Your post has been shared", exact=False)


@patch("reachly.platforms.instagram.persistent_page")
def test_instagram_wrong_bound_account_never_opens_composer(context):
    page = context.return_value.__enter__.return_value
    page.get_by_role.return_value.count.return_value = 1
    page.get_by_role.return_value.get_attribute.return_value = "/other-account/"
    poster = InstagramBrowserPoster(PlatformCredentials(platform=Platform.instagram, mode=PlatformMode.browser,
        extra={"expected_account": "demo_clinic"}), data_dir=Path("/unused"))
    poster._needs_login = MagicMock(return_value=False)
    poster._open_create = MagicMock()
    post = GeneratedPost(theme="demo", hook="", body="Approved", media=GeneratedMedia(kind="image", local_path="/unused.png"))
    assert not poster.post(post).ok
    poster._open_create.assert_not_called()
