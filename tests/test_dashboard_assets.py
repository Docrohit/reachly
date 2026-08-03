from fastapi.testclient import TestClient

from reachly.config import AgentConfig
from reachly.dashboard import app as dashboard_app
from reachly.storage import History


def test_dashboard_lists_and_downloads_recent_assets(tmp_path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    image = media_dir / "asset.png"
    image.write_bytes(b"image-bytes")

    history = History(tmp_path)
    history.record(
        theme="catalog ops",
        hook="Use generated assets everywhere",
        body="Body",
        platform="linkedin",
        ok=True,
        media_kind="image",
        media_local_path=str(image),
        post_text="Copy-ready dashboard text",
    )
    history.close()

    dashboard_app._cfg = AgentConfig(
        {
            "DATA_DIR": str(tmp_path),
            "REACHLY_DASHBOARD_TOKEN": "",
            "DRY_RUN": "true",
        }
    )
    try:
        client = TestClient(dashboard_app.create_app())
        page = client.get("/?assets=48")
        assert page.status_code == 200
        assert "Creative assets" in page.text
        assert "Copy-ready dashboard text" in page.text
        assert "/assets/1/media" in page.text

        download = client.get("/assets/1/media?download=true")
        assert download.status_code == 200
        assert download.content == b"image-bytes"

        archive = client.get("/assets/archive?hours=48")
        assert archive.status_code == 200
        assert archive.headers["content-type"] == "application/zip"
    finally:
        dashboard_app._cfg = None
