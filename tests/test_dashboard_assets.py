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


def test_dashboard_supports_forwarded_prefix_for_public_subpath(tmp_path):
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
            "REACHLY_DASHBOARD_TOKEN": "secret-token",
            "DRY_RUN": "true",
        }
    )
    try:
        client = TestClient(dashboard_app.create_app())
        headers = {"x-forwarded-prefix": "/hygaar-dashboard"}

        unauthenticated = client.get("/", headers=headers)
        assert unauthenticated.status_code == 401
        assert 'action="/hygaar-dashboard/auth"' in unauthenticated.text

        auth = client.post(
            "/auth",
            headers=headers,
            data={"token": "secret-token"},
            follow_redirects=False,
        )
        assert auth.status_code == 303
        assert auth.headers["location"] == "/hygaar-dashboard/"

        page = client.get(
            "/?assets=48",
            headers={**headers, "x-reachly-token": "secret-token"},
        )
        assert page.status_code == 200
        assert "/hygaar-dashboard/assets/1/media" in page.text
        assert 'href="/hygaar-dashboard/?assets=24"' in page.text
        assert 'fetch(`${basePath}/run-now`' in page.text
    finally:
        dashboard_app._cfg = None
