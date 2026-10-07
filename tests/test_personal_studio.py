import json
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, select

from reachly.models import GeneratedPost, GeneratedMedia, PostResult, Platform
from reachly.storage import History


@pytest.fixture
def personal(tmp_path, monkeypatch):
    from server import app as web, db, orchestrator, studio
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db, "engine", engine)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(web.settings, "media_dir", str(tmp_path / "media"))
    monkeypatch.setattr(web.settings, "vault_key", Fernet.generate_key().decode())
    monkeypatch.setattr(web.settings, "legacy_auth_enabled", False)
    monkeypatch.setattr(web.settings, "telegram_login_enabled", True)
    monkeypatch.setattr(orchestrator, "get_settings", lambda: web.settings)
    from server.crypto import encrypt_dict
    with db.get_session() as session:
        user = db.User(telegram_chat_id="42", is_active=True, dry_run=True)
        session.add(user); session.commit(); session.refresh(user)
        profile = db.BusinessProfileRow(user_id=user.id, name="Independent Bakery", website="https://bakery.example", providers_vault=encrypt_dict({"gemini_api_key": "synthetic"}))
        session.add(profile); session.commit(); session.refresh(user)
    client = TestClient(web.app)
    with patch("server.app.verify_otp", return_value=(True, user.id)):
        assert client.post("/auth/verify", data={"handle": "test", "code": "123456"}).status_code == 200
    yield client, user, web, db, studio
    engine.dispose()


def test_personal_login_and_pages_have_no_work_brand(personal):
    client, user, web, db, studio = personal
    for path in ("/", "/login", "/studio", "/dashboard", "/profile", "/billing", "/analytics", "/dashboard/assets"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        assert "hygaar" not in response.text.lower(), path
    with patch("server.app.login_with_hygaar") as bridge:
        assert client.post("/auth/hygaar/login", data={"email": "person@example.com", "password": "unused"}).status_code == 404
        bridge.assert_not_called()


def test_project_inputs_research_and_generation_are_business_scoped(personal):
    client, user, web, db, studio = personal
    assert client.post("/studio/inputs", data={"project_notes": "SaaS2point0 positioning: local bread subscriptions", "research_notes": "Source: https://bakery.example", "performance_notes": "10 real posts; 100 measured clicks"}).status_code == 200
    from server.orchestrator import build_agent_for_user
    agent = build_agent_for_user(user)
    try:
        context = agent._strategy.for_prompt()
        assert "bread subscriptions" in context and "100 measured clicks" in context
        assert not agent.settings.allow_local_context
    finally:
        agent.close()
    evidence = {"sources": [{"url": "https://bakery.example", "title": "Bakery"}], "findings": [{"summary": "Bread is available."}]}
    with patch("server.studio.research_business", return_value=evidence) as research:
        assert client.post("/studio/research").status_code == 200
        assert research.call_args.args[0].business.name == "Independent Bakery"
    post = GeneratedPost(theme="Bread", hook="Fresh every morning", body="Our bakery makes bread.")
    with patch("reachly.agent.Agent.build_post", return_value=post), patch("reachly.agent.Agent._publish") as publisher:
        assert client.post("/studio/generate", data={"topic": "Bread"}).status_code == 200
        publisher.assert_not_called()
    with db.get_session() as session:
        draft = session.exec(select(studio.StudioDraft)).one()
        assert draft.state == "draft"
    assert "Fresh every morning" in client.get("/studio").text
    assert client.post(f"/studio/{draft.id}/publish", data={"platform": "linkedin", "confirm": "publish"}).status_code == 422


def test_publication_is_claimed_once_and_drafts_cannot_cross_accounts(personal, monkeypatch):
    client, user, web, db, studio = personal
    from server.crypto import encrypt_dict
    with db.get_session() as session:
        profile = session.exec(select(db.BusinessProfileRow)).one()
        draft = studio.StudioDraft(user_id=user.id, business_key=studio._key(profile), content=GeneratedPost(theme="Bread", hook="Bread", body="Fresh bread.").model_dump_json())
        session.add(draft)
        session.add(db.PlatformCredRow(user_id=user.id, platform="linkedin", mode="api", vault=encrypt_dict({"access_token": "synthetic"})))
        session.commit(); session.refresh(draft)
    with db.get_session() as session:
        row = session.get(db.User, user.id); row.dry_run = False; session.add(row); session.commit()
    results = {Platform.linkedin: PostResult(platform=Platform.linkedin, ok=True, permalink="https://www.linkedin.com/feed/update/urn:li:share:123")}
    with patch("reachly.agent.Agent._publish", return_value=results) as publisher:
        assert client.post(f"/studio/{draft.id}/publish", data={"platform": "linkedin", "confirm": "publish"}).status_code == 200
        assert client.post(f"/studio/{draft.id}/publish", data={"platform": "linkedin", "confirm": "publish"}).status_code == 409
        assert publisher.call_count == 1
    other = db.User(id=999, telegram_chat_id="99", is_active=True)
    with db.get_session() as session:
        session.add(other); session.commit()
    with patch("server.app.verify_otp", return_value=(True, 999)):
        client.post("/auth/verify", data={"handle": "other", "code": "123456"})
    assert client.get(f"/studio/{draft.id}/media").status_code == 404
    assert client.post(f"/studio/{draft.id}/publish", data={"platform": "linkedin", "confirm": "publish"}).status_code == 404


def test_media_assets_and_feedback_survive_the_combined_source(personal, tmp_path):
    client, user, web, db, studio = personal
    folder = web._user_agent_dir(user.id)
    folder.mkdir(parents=True, exist_ok=True)
    image = folder / "image.png"; image.write_bytes(b"image")
    history = History(folder)
    history.record(theme="Bread", hook="Fresh bread", body="Today's bake", platform="linkedin", ok=True, permalink="https://example.com/post", media_kind="image", media_local_path=str(image))
    history.close()
    assert "Fresh bread" in client.get("/dashboard/assets").text
    assert client.get("/dashboard/assets/media/1").content == b"image"
    assert client.post("/analytics/1", data={"impressions": "150", "likes": "12"}).status_code == 200
    assert "150" in client.get("/analytics").text
    from server.orchestrator import build_agent_for_user
    agent = build_agent_for_user(user)
    try:
        assert "150" in agent.analytics_review()
    finally:
        agent.close()
    assert client.post("/analytics/1", data={"likes": "-2"}).status_code == 422
    forbidden = tmp_path / "outside.png"; forbidden.write_bytes(b"private")
    assert web._resolve_user_media(folder, str(forbidden)) is None


def test_business_switch_disables_schedule_and_platforms(personal):
    client, user, web, db, studio = personal
    with db.get_session() as session:
        row = session.get(db.User, user.id); row.scheduler_enabled = True; row.dry_run = False
        session.add(row); session.add(db.PlatformCredRow(user_id=user.id, platform="linkedin", mode="api")); session.commit()
    assert client.post("/dashboard/profile", data={"name": "A different service", "website": "https://service.example"}).status_code == 200
    with db.get_session() as session:
        row = session.get(db.User, user.id)
        assert row.dry_run and not row.scheduler_enabled
        assert session.exec(select(db.PlatformCredRow)).one().mode == "off"


def test_repo_context_cannot_discover_other_workspace_docs(tmp_path):
    from reachly.context import load_strategy_context
    (tmp_path / "AGENTS.md").write_text("OTHER COMPANY SECRET")
    (tmp_path / "product_theory.md").write_text("OTHER COMPANY STRATEGY")
    child = tmp_path / "personal"; child.mkdir()
    context = load_strategy_context(data_dir=child / "data", context_repo=str(child))
    assert "OTHER COMPANY" not in context.for_prompt()


def test_two_businesses_keep_credentials_content_and_switching_separate(personal):
    client, user, web, db, studio = personal
    assert client.post("/workspaces", data={"name": "Council of AI", "website": "https://councilofai.nftforger.com"}).status_code == 200
    assert client.post("/studio/inputs", data={"project_notes": "Council of AI facts only"}).status_code == 200
    with db.get_session() as session:
        first = session.exec(select(db.User).where(db.User.owner_user_id == user.id)).one()
        first_id = first.id
    assert client.post("/workspaces", data={"name": "Council Network", "website": "https://councilnetwork.nftforger.com"}).status_code == 200
    assert "Council of AI facts only" not in client.get("/studio").text
    assert "Council Network" in client.get("/studio").text
    assert client.post(f"/workspaces/{first_id}/switch").status_code == 200
    assert "Council of AI facts only" in client.get("/studio").text
    with db.get_session() as session:
        other = db.User(telegram_chat_id="stranger", is_active=True)
        session.add(other); session.commit(); session.refresh(other); other_id = other.id
    assert client.post(f"/workspaces/{other_id}/switch").status_code == 404
    with db.get_session() as session:
        assert session.get(db.User, first_id).scheduler_enabled is False
