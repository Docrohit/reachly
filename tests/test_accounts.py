import re
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, select

from reachly.models import GeneratedPost


@pytest.fixture
def env(tmp_path, monkeypatch):
    from server import accounts, app as web, channels, crypto, db, orchestrator
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db, "engine", engine)
    SQLModel.metadata.create_all(engine)
    s = web.settings
    for name, value in {"media_dir": str(tmp_path / "media"), "vault_key": Fernet.generate_key().decode(),
                        "legacy_auth_enabled": False, "telegram_login_enabled": True,
                        "public_base_url": "https://reachly.example", "x_client_id": "x", "x_client_secret": "y",
                        "smtp_host": "smtp.example", "smtp_from": "Reachly <bot@example.com>"}.items():
        monkeypatch.setattr(s, name, value)
    for module in (orchestrator, crypto, channels, accounts):
        monkeypatch.setattr(module, "get_settings", lambda: s)
    sent = []
    monkeypatch.setattr(accounts, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    with db.get_session() as session:
        owner = db.User(telegram_chat_id="42", is_active=True, dry_run=True)
        session.add(owner); session.commit(); session.refresh(owner)
        other = db.User(owner_user_id=owner.id, telegram_chat_id="workspace:a", auth_provider="workspace", is_active=True)
        lead = db.User(owner_user_id=owner.id, telegram_chat_id="workspace:b", auth_provider="workspace", is_active=True)
        session.add(other); session.add(lead); session.commit()
        for row, name in ((owner, "Council of AI"), (other, "Council Network"), (lead, "Lead Cafe")):
            session.refresh(row)
            session.add(db.BusinessProfileRow(user_id=row.id, name=name, website=f"https://{name.split()[0].lower()}.example"))
        session.commit()
        ids = (owner.id, other.id, lead.id)
    yield web, db, accounts, channels, sent, ids
    engine.dispose()


def _telegram_login(web, user_id):
    client = TestClient(web.app)
    with patch("server.app.verify_otp", return_value=(True, user_id)):
        assert client.post("/auth/verify", data={"handle": "t", "code": "123456"}).status_code == 200
    return client


def _code(sent):
    return re.search(r"\b(\d{6})\b", sent[-1][2]).group(1)


def _email_login(web, sent, email):
    client = TestClient(web.app)
    page = client.post("/auth/email/start", data={"email": email})
    assert page.status_code == 200 and "6-digit code" in page.text
    return client, client.post("/auth/email/verify", data={"email": email, "code": _code(sent)}, follow_redirects=False)


def test_owner_links_email_then_signs_in_with_a_code(env):
    web, db, accounts, channels, sent, (owner_id, *_rest) = env
    client = _telegram_login(web, owner_id)
    assert client.post("/account/email/start", data={"email": "Rohit@Example.com"}).status_code == 200
    assert sent[-1][0] == "rohit@example.com"
    assert client.post("/account/email/confirm", data={"email": "rohit@example.com", "code": "000000"},
                       follow_redirects=False).headers["location"].endswith("error=code")
    done = client.post("/account/email/confirm", data={"email": "rohit@example.com", "code": _code(sent)})
    assert "You can now sign in with rohit@example.com" in done.text
    fresh, result = _email_login(web, sent, "rohit@example.com")
    assert result.status_code == 303 and result.headers["location"] == "/channels"
    assert fresh.get("/channels").status_code == 200


def test_unknown_email_gets_same_reply_and_no_email(env):
    web, db, accounts, channels, sent, _ = env
    page = TestClient(web.app).post("/auth/email/start", data={"email": "stranger@example.com"})
    assert page.status_code == 200 and "If stranger@example.com can sign in" in page.text
    assert sent == []


def test_codes_lock_after_five_wrong_attempts_and_hourly_limit(env):
    web, db, accounts, channels, sent, (owner_id, *_rest) = env
    with db.get_session() as session:
        session.add(accounts.EmailIdentity(email="me@example.com", user_id=owner_id)); session.commit()
    client = TestClient(web.app)
    client.post("/auth/email/start", data={"email": "me@example.com"})
    good = _code(sent)
    for _ in range(5):
        assert client.post("/auth/email/verify", data={"email": "me@example.com", "code": "999999"}).status_code == 401
    assert client.post("/auth/email/verify", data={"email": "me@example.com", "code": good}).status_code == 401
    for _ in range(6):
        client.post("/auth/email/start", data={"email": "me@example.com"})
    assert len(sent) == 5  # hourly limit


def test_invited_client_sees_only_their_project(env):
    web, db, accounts, channels, sent, (owner_id, other_id, lead_id) = env
    owner = _telegram_login(web, owner_id)
    assert owner.post(f"/channels/{lead_id}/clients", data={"email": "owner@leadcafe.example"},
                      follow_redirects=False).headers["location"].startswith("/channels?notice=invited")
    assert "Lead Cafe" in sent[-1][1] and "https://reachly.example/login" in sent[-1][2]
    assert "owner@leadcafe.example" in owner.get("/channels").text
    client, result = _email_login(web, sent, "owner@leadcafe.example")
    assert result.headers["location"] == "/client"
    portal = client.get("/client")
    assert portal.status_code == 200 and "Lead Cafe" in portal.text and "Council" not in portal.text
    for path in ("/channels", "/studio", "/workspaces", "/account/email"):
        assert client.get(path, follow_redirects=False).status_code in (401, 303), path
    assert client.get(f"/channels/{other_id}/connect/x", follow_redirects=False).status_code == 404
    start = client.get(f"/channels/{lead_id}/connect/x", follow_redirects=False)
    assert start.status_code == 303 and start.headers["location"].startswith("https://x.com/i/oauth2/authorize")
    # The owner cannot complete a client's OAuth flow (state is bound to who started it).
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    with patch.object(channels, "_http", side_effect=AssertionError("must not call provider")):
        assert "error=cancelled" in owner.get(f"/channels/oauth/x/callback?state={state}&code=c",
                                              follow_redirects=False).headers["location"]


def test_client_x_connection_returns_to_portal(env):
    web, db, accounts, channels, sent, (owner_id, _other, lead_id) = env
    owner = _telegram_login(web, owner_id)
    owner.post(f"/channels/{lead_id}/clients", data={"email": "c@lead.example"})
    client, _ = _email_login(web, sent, "c@lead.example")
    start = client.get(f"/channels/{lead_id}/connect/x", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    def fake_http(method, url, **kwargs):
        if url.endswith("/oauth2/token"):
            return {"access_token": "a", "refresh_token": "r", "expires_in": 7200}
        return {"data": {"id": "5", "username": "leadcafe"}}

    with patch.object(channels, "_http", side_effect=fake_http):
        done = client.get(f"/channels/oauth/x/callback?state={state}&code=c", follow_redirects=False)
    assert done.headers["location"].startswith("/client?notice=connected")
    assert channels.connections(lead_id)["twitter"]["account"] == "@leadcafe"


def test_client_review_holds_draft_from_autopilot_and_removal_revokes(env):
    web, db, accounts, channels, sent, (owner_id, _other, lead_id) = env
    from server.studio import StudioDraft, _key
    with db.get_session() as session:
        profile = session.exec(select(db.BusinessProfileRow).where(db.BusinessProfileRow.user_id == lead_id)).one()
        draft = StudioDraft(user_id=lead_id, business_key=_key(profile), created_at=datetime.now(timezone.utc),
                            content=GeneratedPost(theme="t", hook="Fresh bread at 7", body="Body").model_dump_json())
        session.add(draft); session.commit(); session.refresh(draft)
    owner = _telegram_login(web, owner_id)
    owner.post(f"/channels/{lead_id}/clients", data={"email": "c@lead.example"})
    client, _ = _email_login(web, sent, "c@lead.example")
    assert [d.id for d in channels._queue(lead_id, need_image=False)] == [draft.id]
    client.post(f"/client/drafts/{draft.id}/review", data={"decision": "changes", "note": "Use our logo"})
    assert channels._queue(lead_id, need_image=False) == []
    assert "Client asked for changes" in owner.get("/channels").text and "Use our logo" in owner.get("/channels").text
    owner.post(f"/channels/{lead_id}/clients/remove", data={"email": "c@lead.example"})
    assert client.get("/client").status_code == 401


def test_email_cannot_be_reused_across_roles(env):
    web, db, accounts, channels, sent, (owner_id, _other, lead_id) = env
    owner = _telegram_login(web, owner_id)
    owner.post(f"/channels/{lead_id}/clients", data={"email": "c@lead.example"})
    assert owner.post("/account/email/start", data={"email": "c@lead.example"},
                      follow_redirects=False).headers["location"].endswith("error=used")
    assert "invite_used" in owner.post(f"/channels/{lead_id}/clients", data={"email": "c@lead.example"},
                                       follow_redirects=False).headers["location"]
