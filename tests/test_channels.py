from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, select

from reachly.models import GeneratedMedia, GeneratedPost, Platform, PostResult


@pytest.fixture
def env(tmp_path, monkeypatch):
    from server import app as web, channels, crypto, db, orchestrator
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db, "engine", engine)
    SQLModel.metadata.create_all(engine)
    s = web.settings
    for name, value in {"media_dir": str(tmp_path / "media"), "vault_key": Fernet.generate_key().decode(),
                        "legacy_auth_enabled": False, "telegram_login_enabled": True,
                        "public_base_url": "https://reachly.example", "meta_app_id": "111", "meta_app_secret": "meta-secret",
                        "meta_login_config_id": "", "meta_graph_version": "v25.0",
                        "x_client_id": "x-client", "x_client_secret": "x-secret"}.items():
        monkeypatch.setattr(s, name, value)
    for module in (orchestrator, crypto, channels):
        monkeypatch.setattr(module, "get_settings", lambda: s)
    from server.crypto import encrypt_dict
    with db.get_session() as session:
        owner = db.User(telegram_chat_id="42", is_active=True, dry_run=True)
        session.add(owner); session.commit(); session.refresh(owner)
        session.add(db.BusinessProfileRow(user_id=owner.id, name="Council of AI", website="https://council.example",
                                          providers_vault=encrypt_dict({"gemini_api_key": "synthetic"})))
        session.commit(); session.refresh(owner)
    client = TestClient(web.app)
    with patch("server.app.verify_otp", return_value=(True, owner.id)):
        assert client.post("/auth/verify", data={"handle": "t", "code": "123456"}).status_code == 200
    yield client, owner, db, channels
    engine.dispose()


def _live(db, user_id, live=True):
    with db.get_session() as session:
        row = session.get(db.User, user_id)
        row.dry_run = not live
        session.add(row); session.commit()


def _connect_x(client, owner, channels):
    start = client.get(f"/channels/{owner.id}/connect/x", follow_redirects=False)
    assert start.status_code == 303
    query = parse_qs(urlparse(start.headers["location"]).query)
    assert query["redirect_uri"] == ["https://reachly.example/channels/oauth/x/callback"]
    assert query["code_challenge_method"] == ["S256"] and "offline.access" in query["scope"][0]
    calls = []

    def fake_http(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/oauth2/token"):
            return {"access_token": "x-access", "refresh_token": "x-refresh", "expires_in": 7200}
        if url.endswith("/users/me"):
            return {"data": {"id": "777", "username": "agents_council"}}
        raise AssertionError(url)

    with patch.object(channels, "_http", side_effect=fake_http):
        done = client.get(f"/channels/oauth/x/callback?state={query['state'][0]}&code=abc", follow_redirects=False)
    assert done.status_code == 303 and "notice=connected" in done.headers["location"]
    assert calls[0][2]["data"]["code_verifier"]
    return calls


def _connect_meta(client, owner, channels, pages):
    start = client.get(f"/channels/{owner.id}/connect/meta", follow_redirects=False)
    query = parse_qs(urlparse(start.headers["location"]).query)
    assert "pages_manage_posts" in query["scope"][0] and query["client_id"] == ["111"]

    def fake_http(method, url, **kwargs):
        if url.endswith("oauth/access_token"):
            return {"access_token": "user-token"}
        if url.endswith("me/accounts"):
            assert kwargs["params"]["appsecret_proof"]
            return {"data": pages}
        raise AssertionError(url)

    with patch.object(channels, "_http", side_effect=fake_http):
        return client.get(f"/channels/oauth/meta/callback?state={query['state'][0]}&code=abc", follow_redirects=False)


def _draft(db, owner_id, with_image=True, age=timedelta()):
    from server.studio import StudioDraft, _key
    media = GeneratedMedia(kind="image", local_path="/tmp/img.png", public_url="https://reachly.example/media/img.png",
                           mime_type="image/png") if with_image else None
    post = GeneratedPost(theme="t", hook="Councils of AI agents debate better", body="Body text", media=media)
    with db.get_session() as session:
        profile = session.exec(select(db.BusinessProfileRow).where(db.BusinessProfileRow.user_id == owner_id)).first()
        draft = StudioDraft(user_id=owner_id, business_key=_key(profile), content=post.model_dump_json(),
                            created_at=datetime.now(timezone.utc) - age)
        session.add(draft); session.commit(); session.refresh(draft)
        return draft


def test_page_lists_projects_without_work_brand(env):
    client, owner, db, channels = env
    page = client.get("/channels")
    assert page.status_code == 200
    assert "Council of AI" in page.text and "Connect Facebook" in page.text and "Connect X" in page.text
    assert "hygaar" not in page.text.lower()


def test_x_oauth_binds_tokens_and_replaces_old_keys(env):
    client, owner, db, channels = env
    from server.crypto import decrypt_dict, encrypt_dict
    with db.get_session() as session:
        session.add(db.PlatformCredRow(user_id=owner.id, platform="twitter", mode="api",
                                       vault=encrypt_dict({"consumer_key": "old", "access_token_secret": "old"})))
        session.commit()
    _connect_x(client, owner, channels)
    with db.get_session() as session:
        row = session.exec(select(db.PlatformCredRow).where(db.PlatformCredRow.platform == "twitter")).one()
    data = decrypt_dict(row.vault)
    assert data["oauth2_token"] == "x-access" and data["account"] == "@agents_council"
    assert "consumer_key" not in data
    assert channels.connections(owner.id)["twitter"]["account"] == "@agents_council"


def test_oauth_state_is_single_use_and_owner_bound(env):
    client, owner, db, channels = env
    start = client.get(f"/channels/{owner.id}/connect/x", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    with patch.object(channels, "_http", return_value={}):
        assert "error=cancelled" in client.get(f"/channels/oauth/x/callback?state={state}&error=access_denied",
                                               follow_redirects=False).headers["location"]
        assert "error=cancelled" in client.get(f"/channels/oauth/x/callback?state={state}&code=abc",
                                               follow_redirects=False).headers["location"]


def test_meta_connects_page_and_linked_instagram(env):
    client, owner, db, channels = env
    done = _connect_meta(client, owner, channels, [{"id": "123", "name": "Council Network", "access_token": "page-token",
                                                    "tasks": ["CREATE_CONTENT"],
                                                    "instagram_business_account": {"id": "456", "username": "councilnetwork"}}])
    assert "notice=connected" in done.headers["location"]
    linked = channels.connections(owner.id)
    assert linked["facebook"]["account"] == "Council Network" and linked["instagram"]["account"] == "@councilnetwork"


def test_meta_with_several_pages_asks_which_one(env):
    client, owner, db, channels = env
    pages = [{"id": "1", "name": "Page One", "access_token": "a"}, {"id": "2", "name": "Page Two", "access_token": "b"}]
    done = _connect_meta(client, owner, channels, pages)
    assert "/meta/pick?pick=" in done.headers["location"]
    pick = parse_qs(urlparse(done.headers["location"]).query)["pick"][0]
    assert "Page Two" in client.get(done.headers["location"]).text
    saved = client.post(f"/channels/{owner.id}/meta/pick", data={"pick": pick, "page_id": "2"}, follow_redirects=False)
    assert saved.status_code == 303
    assert channels.connections(owner.id)["facebook"]["account"] == "Page Two"
    assert "instagram" not in channels.connections(owner.id)


def _connected_all(client, owner, channels):
    _connect_meta(client, owner, channels, [{"id": "123", "name": "Council Network", "access_token": "page-token",
                                             "instagram_business_account": {"id": "456", "username": "cn"}}])
    _connect_x(client, owner, channels)


def test_publish_to_several_channels_once_each(env):
    client, owner, db, channels = env
    _connected_all(client, owner, channels)
    draft = _draft(db, owner.id)
    assert client.post(f"/channels/{owner.id}/drafts/{draft.id}/publish", data={"platforms": ["facebook"]}).status_code == 422
    _live(db, owner.id)
    sent = []

    def fake_publish(self, post, platforms=None):
        target = platforms[0]
        sent.append(target)
        return {target: PostResult(platform=target, ok=True, permalink=f"https://{target.value}.example/1")}

    with patch("reachly.agent.Agent._publish", fake_publish), \
         patch("server.x_engagement.guarded_send", side_effect=lambda user, text, publish=None, **kw: publish()):
        result = channels.publish_draft(owner, draft.id, ["facebook", "instagram", "twitter"])
        assert result == {"facebook": "published", "instagram": "published", "twitter": "published"}
        again = channels.publish_draft(owner, draft.id, ["facebook"])
    assert again == {"facebook": "skipped"}
    assert sent == [Platform.facebook, Platform.instagram, Platform.twitter]
    assert channels.last_published_at(owner.id) is not None


def test_definite_refusal_can_retry_but_unknown_outcome_cannot(env):
    client, owner, db, channels = env
    _connected_all(client, owner, channels)
    _live(db, owner.id)
    draft = _draft(db, owner.id)
    replies = {Platform.facebook: PostResult(platform=Platform.facebook, ok=False, error="rejected: Facebook refused"),
               Platform.instagram: PostResult(platform=Platform.instagram, ok=False, error="timeout")}
    with patch("reachly.agent.Agent._publish", lambda self, post, platforms=None: {platforms[0]: replies[platforms[0]]}):
        assert channels.publish_draft(owner, draft.id, ["facebook", "instagram"]) == {"facebook": "failed", "instagram": "check_platform"}
        replies[Platform.facebook] = PostResult(platform=Platform.facebook, ok=True, permalink="https://facebook.com/1")
        assert channels.publish_draft(owner, draft.id, ["facebook", "instagram"]) == {"facebook": "published", "instagram": "skipped"}


def test_autopilot_publishes_oldest_draft_when_due_and_waits_otherwise(env):
    client, owner, db, channels = env
    _connected_all(client, owner, channels)
    _live(db, owner.id)
    old = _draft(db, owner.id, age=timedelta(hours=5))
    _draft(db, owner.id, age=timedelta(hours=1))
    client.post(f"/channels/{owner.id}/autopilot", data={"enabled": "on", "platforms": ["facebook", "instagram"]})
    published = []

    def fake_publish(workspace, draft_id, platforms, trigger="manual"):
        published.append((draft_id, tuple(platforms), trigger))
        with db.get_session() as session:
            session.add(db.PostLogRow(user_id=owner.id, platform="facebook", ok=True, permalink="https://facebook.com/1"))
            session.commit()
        return {p: "published" for p in platforms}

    with patch.object(channels, "publish_draft", side_effect=fake_publish), \
         patch.object(channels, "generate_draft", side_effect=AssertionError("queue should be used")):
        channels.autopilot_tick()
        assert published == [(old.id, ("facebook", "instagram"), "autopilot")]
        channels.autopilot_tick()  # just published: not due for 24 hours
    assert len(published) == 1
    with db.get_session() as session:
        fresh = session.get(db.User, owner.id)
    assert "less than 24 hours" in channels.due_reason(fresh, channels.autopilot_setting(owner.id), datetime.utcnow())


def test_autopilot_generates_when_queue_is_empty_and_respects_live_switch(env):
    client, owner, db, channels = env
    _connected_all(client, owner, channels)
    client.post(f"/channels/{owner.id}/autopilot", data={"enabled": "on", "platforms": ["twitter"]})
    generated = _draft(db, owner.id)
    with db.get_session() as session:
        from server.studio import StudioDraft
        row = session.get(StudioDraft, generated.id); row.state = "discarded"; session.add(row); session.commit()
    with patch.object(channels, "generate_draft", return_value=generated) as gen, \
         patch.object(channels, "publish_draft", return_value={"twitter": "published"}) as pub:
        assert channels.run_cycle(owner.id) == "Live publishing is off for this project."
        gen.assert_not_called()
        _live(db, owner.id)
        channels.run_cycle(owner.id)
    gen.assert_called_once()
    pub.assert_called_once_with(pub.call_args.args[0], generated.id, ["twitter"], trigger="autopilot")
    assert channels.autopilot_setting(owner.id).status == "published"


def test_x_token_refreshes_before_expiry_with_rotation(env):
    client, owner, db, channels = env
    _connect_x(client, owner, channels)
    from server.crypto import decrypt_dict, encrypt_dict
    with db.get_session() as session:
        row = session.exec(select(db.PlatformCredRow).where(db.PlatformCredRow.platform == "twitter")).one()
        data = decrypt_dict(row.vault); data["oauth2_expires_at"] = datetime.utcnow().isoformat()
        row.vault = encrypt_dict(data); session.add(row); session.commit(); session.refresh(row)
    with patch.object(channels, "_http", return_value={"access_token": "new", "refresh_token": "rotated", "expires_in": 7200}) as call:
        fresh = channels.refresh_x_token(row)
    assert call.call_args.kwargs["data"]["refresh_token"] == "x-refresh"
    data = decrypt_dict(fresh.vault)
    assert data["oauth2_token"] == "new" and data["oauth2_refresh_token"] == "rotated"


def test_facebook_api_poster_posts_photo_with_appsecret_proof(tmp_path):
    from reachly.models import PlatformCredentials, PlatformMode
    from reachly.platforms.facebook import FacebookApiPoster
    image = tmp_path / "img.png"; image.write_bytes(b"png")
    post = GeneratedPost(theme="t", hook="Hook", body="Body", media=GeneratedMedia(kind="image", local_path=str(image), mime_type="image/png"))
    creds = PlatformCredentials(platform=Platform.facebook, mode=PlatformMode.api, api_token="page-token",
                                extra={"page_id": "123", "app_secret": "s"})

    class Response:
        status_code, ok = 200, True
        def json(self): return {"id": "9", "post_id": "123_9"}

    with patch("reachly.platforms.facebook.requests.post", return_value=Response()) as call:
        result = FacebookApiPoster(creds).post(post)
    assert result.ok and result.permalink == "https://www.facebook.com/123_9"
    assert call.call_args.args[0].endswith("/123/photos") and call.call_args.kwargs["params"]["appsecret_proof"]
