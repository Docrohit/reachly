from pathlib import Path
from unittest.mock import MagicMock, patch
from reachly.models import GeneratedPost, Platform, PlatformCredentials, PlatformMode
from reachly.platforms.facebook import FacebookBrowserPoster


def poster():
    return FacebookBrowserPoster(PlatformCredentials(platform=Platform.facebook, mode=PlatformMode.browser,
        extra={"expected_account": "Demo Clinic", "page_url": "https://www.facebook.com/demo-clinic"}), data_dir=Path("/unused/test-profile"))


@patch("reachly.platforms.facebook.persistent_page")
def test_unverified_composer_actor_never_clicks_post(context):
    page = context.return_value.__enter__.return_value
    page.locator.return_value.count.return_value = 0
    dialog = page.get_by_role.return_value.filter.return_value.last
    dialog.get_by_role.return_value.count.return_value = 0
    result = poster().post(GeneratedPost(theme="demo", hook="", body="Approved caption"))
    assert not result.ok
    dialog.get_by_role.return_value.click.assert_not_called()


@patch("reachly.platforms.facebook.persistent_page")
def test_post_click_without_confirmation_is_not_success(context):
    page = context.return_value.__enter__.return_value
    page.locator.return_value.count.return_value = 0
    dialog = page.get_by_role.return_value.filter.return_value.last
    dialog.get_by_role.return_value.count.return_value = 1
    page.get_by_text.return_value.first.wait_for.side_effect = TimeoutError("No confirmation")
    result = poster().post(GeneratedPost(theme="demo", hook="", body="Approved caption"))
    assert not result.ok
    dialog.get_by_role.return_value.click.assert_called_once()


@patch("reachly.platforms.facebook.persistent_page")
def test_platform_confirmation_marks_success(context):
    page = context.return_value.__enter__.return_value
    page.locator.return_value.count.return_value = 0
    dialog = page.get_by_role.return_value.filter.return_value.last
    dialog.get_by_role.return_value.count.return_value = 1
    result = poster().post(GeneratedPost(theme="demo", hook="", body="Approved caption"))
    assert result.ok
    page.get_by_text.assert_called_once_with("Your post is now published", exact=False)
