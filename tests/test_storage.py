from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from reachly.agent import Agent, AgentSettings
from reachly.models import BusinessProfile
from reachly.storage import History


def test_history_can_be_used_from_scheduler_threads(tmp_path):
    history = History(tmp_path)
    history.record(
        theme="AI",
        hook="Why catalog teams need media agents",
        body="Body",
        platform="linkedin",
        ok=True,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        hooks = executor.submit(history.recent_hooks).result()
        executor.submit(
            history.record_event,
            platform="instagram",
            ok=False,
            error="scheduled failure",
        ).result()

    assert hooks == ["Why catalog teams need media agents"]
    history.close()


def test_history_migrates_and_summarizes_analytics(tmp_path):
    history = History(tmp_path)
    history.record(
        theme="catalog ops",
        hook="The fastest PDP teams do not brief images one by one",
        body="Body",
        platform="linkedin",
        ok=True,
        impressions=1200,
        likes=38,
        comments=4,
        shares=2,
        analytics_note="Strong operator pain-point framing.",
    )
    history.record(
        theme="workflow",
        hook="A shoot list is a product data problem",
        body="Body",
        platform="instagram",
        ok=True,
    )
    history.record_analytics(
        2,
        impressions=700,
        likes=22,
        comments=3,
        note="Carousel-style operational language worked.",
    )

    summary = history.analytics_summary(days=14)
    newness = history.newness_summary(limit_per_platform=3)

    assert "impressions=1200" in summary
    assert "impressions=700" in summary
    assert "Strong operator pain-point framing" in summary
    assert "Carousel-style operational language worked" in summary
    assert "linkedin last 1 posts" in newness
    assert "instagram last 1 posts" in newness
    history.close()


def test_history_tracks_recent_image_post_references(tmp_path):
    history = History(tmp_path)
    low = tmp_path / "low.png"
    high = tmp_path / "high.png"
    low.write_text("low", encoding="utf-8")
    high.write_text("high", encoding="utf-8")
    history.record(
        theme="catalog ops",
        hook="Static catalog work does not scale",
        body="Body",
        platform="linkedin",
        ok=True,
        likes=1,
        media_kind="image",
        media_local_path=str(low),
        media_prompt="catalog image",
    )
    history.record(
        theme="variant launch",
        hook="Launch variants without reshooting every SKU",
        body="Body",
        platform="linkedin",
        ok=True,
        likes=10,
        comments=2,
        media_kind="image",
        media_local_path=str(high),
        media_prompt="variant image",
    )
    history.record(
        theme="video",
        hook="Video record should not be selected",
        body="Body",
        platform="linkedin",
        ok=True,
        media_kind="video",
        media_local_path=str(tmp_path / "video.mp4"),
    )

    rows = history.recent_image_posts(limit=2)

    assert [row["hook"] for row in rows] == [
        "Launch variants without reshooting every SKU",
        "Static catalog work does not scale",
    ]
    assert rows[0]["media_local_path"] == str(high)
    assert rows[0]["media_prompt"] == "variant image"
    history.close()


def test_history_tracks_recent_media_assets_with_copy_text(tmp_path):
    history = History(tmp_path)
    image = tmp_path / "asset.png"
    video = tmp_path / "asset.mp4"
    image.write_text("image", encoding="utf-8")
    video.write_text("video", encoding="utf-8")

    history.record(
        theme="catalog ops",
        hook="Image hook",
        body="Image body",
        platform="linkedin",
        ok=True,
        media_kind="image",
        media_local_path=str(image),
        post_text="Copy-ready image post",
    )
    history.record(
        theme="video ad",
        hook="Video hook",
        body="Video body",
        platform="linkedin",
        ok=True,
        media_kind="video",
        media_local_path=str(video),
        post_text="Copy-ready video post",
    )
    old = (datetime.utcnow() - timedelta(hours=72)).isoformat()
    history._conn.execute("UPDATE posts SET created_at = ? WHERE hook = ?", (old, "Image hook"))
    history._conn.commit()

    assets = history.recent_media_assets(hours=48)

    assert [row["hook"] for row in assets] == ["Video hook"]
    assert assets[0]["media_kind"] == "video"
    assert assets[0]["post_text"] == "Copy-ready video post"
    history.close()


def test_agent_theme_selection_avoids_recent_successful_themes(tmp_path):
    agent = Agent(
        BusinessProfile(
            name="Hygaar",
            content_themes=[
                "fashion catalog automation",
                "ethnic wear photoshoots",
                "western wear launches",
                "jewellery and accessory visuals",
            ],
        ),
        {},
        AgentSettings(data_dir=tmp_path),
    )
    selected = agent._select_theme()
    agent.history.record(
        theme=selected,
        hook="First hook",
        body="Body",
        platform="twitter",
        ok=True,
    )

    next_selected = agent._select_theme()

    assert next_selected != selected
    assert next_selected in agent.business.content_themes
    agent.close()
