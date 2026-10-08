import base64
import io
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from reachly import generation_store as store, generation_worker as worker
from reachly.generation_contract import GenerationRequest
from reachly.models import GeneratedMedia, BusinessProfile
from reachly.agent import Agent, AgentSettings
from server.generation_api import router


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = {"clients": {"clinic-service": {"token_env": "TEST_GENERATION_TOKEN", "business_ids": ["A", "B"], "provider": "shared"},
                          "other-service": {"token_env": "TEST_OTHER_TOKEN", "business_ids": ["A"], "provider": "shared"}},
              "providers": {"shared": {"llm_provider": "gemini", "llm_model": "test-copy", "image_model": "test-image", "gemini_api_key_env": "TEST_PROVIDER_KEY"}}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    monkeypatch.setenv("REACHLY_GENERATION_CONFIG", str(path))
    monkeypatch.setenv("REACHLY_GENERATION_DATA", str(tmp_path / "jobs"))
    monkeypatch.setenv("TEST_GENERATION_TOKEN", "fictional-service-secret")
    monkeypatch.setenv("TEST_OTHER_TOKEN", "fictional-other-secret")
    monkeypatch.setenv("TEST_PROVIDER_KEY", "fictional-provider-key")
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers={"X-Reachly-Client": "clinic-service", "Authorization": "Bearer fictional-service-secret"})


def payload(business="A", logo=False):
    brand = {"colors": ["#123456"], "theme": "Quiet natural light"}
    if logo:
        data = io.BytesIO()
        Image.new("RGB", (10, 10), "red").save(data, "PNG")
        brand["logo_base64"] = base64.b64encode(data.getvalue()).decode()
    return {"business_id": business, "source_version": "revision-1", "context_mode": "clinic_basic", "count": 5,
            "business": {"name": "Fictional Dental" if business == "A" else "Fictional Bakery", "sector": "dentistry" if business == "A" else "bakery", "website": "https://example.test"},
            "brand": brand, "public_facts": {"services": ["Checkups"]}}


def submit(client, data, key=None):
    return client.post("/api/v1/generation-jobs", json=data, headers={"Idempotency-Key": key or str(uuid.uuid4())})


def providers(fail_at=None):
    count = {"copy": 0, "image": 0}
    prompts = []
    def generate(system, prompt):
        prompts.append(prompt)
        if "themes array" in system:
            size = json.loads(prompt)["count"]
            return {"themes": [f"Distinct topic {i}" for i in range(size)]}
        count["copy"] += 1
        return {"theme": "Care advice", "hook": f"Opening {count['copy']}", "body": "Ask your clinic for details.", "hashtags": ["#Care"], "image_prompt": "Illustrative scene", "cta_link": "https://wrong-business.test"}
    def image(prompt, **kwargs):
        count["image"] += 1
        if count["image"] == fail_at:
            raise ValueError("test invalid image response")
        prompts.append(prompt)
        path = kwargs["out_dir"] / "provider.png"
        Image.new("RGB", (128, 128), (0, count["image"], 255)).save(path, "PNG")
        return GeneratedMedia(kind="image", local_path=str(path))
    return generate, image, prompts


def run_worker(fail_at=None):
    generate, image, prompts = providers(fail_at)
    with patch.object(worker.LLMClient, "generate_json", side_effect=generate), patch.object(worker, "generate_image_gemini", side_effect=image):
        worker.process(store.claim())
    return prompts


def test_idempotency_and_scope(client):
    key = str(uuid.uuid4())
    first = submit(client, payload(), key)
    assert first.status_code == 202
    assert submit(client, payload(), key).json()["job_id"] == first.json()["job_id"]
    changed = payload(); changed["count"] = 1
    assert submit(client, changed, key).status_code == 409
    assert submit(client, payload("unassigned")).status_code == 403
    job = first.json()["job_id"]
    assert client.get(f"/api/v1/generation-jobs/{job}", headers={"X-Reachly-Client": "other-service", "Authorization": "Bearer fictional-other-secret"}).status_code == 404
    assert client.get(f"/api/v1/generation-jobs/{job}", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_daily_pair_uses_one_topic_and_two_images(client):
    data = payload()
    data.update(count=2, creative_mode="daily_alternatives", content_type="awareness")
    response = submit(client, data)
    assert response.status_code == 202
    prompts = run_worker()
    result = client.get('/api/v1/generation-jobs/' + response.json()['job_id']).json()
    assert result['state'] == 'completed'
    assert len(result['candidates']) == 2
    assert len({c['post']['theme'] for c in result['candidates']}) == 1
    assert len({c['media_sha256'] for c in result['candidates']}) == 2
    plan = json.loads(prompts[0])
    assert plan['count'] == 1
    assert plan['content_type'] == 'awareness'
    assert plan['requested_topic'] == ''
    data['count'] = 3
    assert submit(client, data).status_code == 422


def test_selected_daily_topic_skips_an_extra_planning_call(client):
    data = payload()
    data.update(count=2, creative_mode="daily_alternatives", content_type="awareness", topic="Routine checkups")
    response = submit(client, data)
    generate, image, _ = providers()
    with patch.object(worker.LLMClient, "generate_json", side_effect=generate) as copy, patch.object(worker, "generate_image_gemini", side_effect=image) as images:
        worker.process(store.claim())
    result = client.get('/api/v1/generation-jobs/' + response.json()['job_id']).json()
    assert copy.call_count == images.call_count == 2
    assert {c['post']['theme'] for c in result['candidates']} == {'Routine checkups'}


def test_daily_pair_selects_one_shared_topic_when_model_returns_two(client, caplog):
    data = payload()
    data.update(count=2, creative_mode="daily_alternatives", content_type="awareness")
    job = submit(client, data).json()["job_id"]
    generate, image, _ = providers()
    def extra_topics(system, prompt):
        if "themes array" in system:
            return {"themes": [" Routine checkups ", "Brushing habits"]}
        return generate(system, prompt)
    with patch.object(worker.LLMClient, "generate_json", side_effect=extra_topics) as copy, patch.object(worker, "generate_image_gemini", side_effect=image) as images:
        worker.process(store.claim())
    result = client.get(f"/api/v1/generation-jobs/{job}").json()
    assert result["state"] == "completed"
    assert result["daily_topic"] == "Routine checkups"
    assert {c["post"]["theme"] for c in result["candidates"]} == {"Routine checkups"}
    assert len({c["media_sha256"] for c in result["candidates"]}) == 2
    assert copy.call_count == 3  # One plan plus two captions; no paid repair call.
    assert images.call_count == 2
    assert "using the first shared topic" in caplog.text
    assert "Routine checkups" not in caplog.text


@pytest.mark.parametrize("plan", [None, [], {"themes": None}, {"themes": "a"}, {"themes": []}, {"themes": [""]}, {"themes": [{}]}, {"themes": ["x" * 256]}])
def test_invalid_daily_plan_fails_before_images_with_stage(client, plan):
    data = payload()
    data.update(count=2, creative_mode="daily_alternatives")
    job = submit(client, data).json()["job_id"]
    with patch.object(worker.LLMClient, "generate_json", return_value=plan), patch.object(worker, "generate_image_gemini") as images:
        worker.process(store.claim())
    result = client.get(f"/api/v1/generation-jobs/{job}").json()
    assert result["state"] == "failed"
    assert result["failed_stage"] == "planning"
    images.assert_not_called()


def test_distinct_post_plan_still_requires_requested_topic_count():
    request = GenerationRequest.model_validate(payload())
    llm = Mock()
    llm.generate_json.return_value = {"themes": ["One", "Two"]}
    with pytest.raises(ValueError, match="Invalid strategy plan"):
        worker.plan_themes(llm, request, {})


def test_real_asset_contract_brand_and_partial_failure(client):
    job = submit(client, payload(logo=True)).json()["job_id"]
    prompts = run_worker(fail_at=3)
    result = client.get(f"/api/v1/generation-jobs/{job}").json()
    assert result["state"] == "partial"
    completed = [c for c in result["candidates"] if c["state"] == "completed"]
    assert len(completed) == 4
    assert len({c["media_sha256"] for c in completed}) == 4
    asset = client.get(f"/api/v1/generation-jobs/{job}/assets/{completed[0]['id']}")
    assert asset.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(asset.content))
    assert image.getpixel((115, 115))[:3] == (255, 0, 0)
    assert completed[0]["post"]["link"] == "https://example.test"
    assert "#123456" in "\n".join(prompts)
    assert "Quiet natural light" in "\n".join(prompts)
    assert "Hygaar" not in "\n".join(prompts)
    assert "fashion" not in "\n".join(prompts).lower()
    assert store.claim() is None  # Finished work is never automatically replayed.


def test_enhanced_missing_audit_and_research_failure(client):
    data = payload(); data.update(context_mode="clinic_enhanced", research_requested=True, count=1)
    job = submit(client, data).json()["job_id"]
    with patch.object(worker, "research_business", side_effect=RuntimeError("unavailable")):
        run_worker()
    result = client.get(f"/api/v1/generation-jobs/{job}").json()
    assert result["state"] == "completed"
    assert len(result["warnings"]) == 2
    assert result["evidence"] == {"geo": None, "research": None}


def test_basic_mode_accepts_geo_but_rejects_research(client):
    data = payload()
    data["geo"] = {"business_id": "B", "captured_at": datetime.now(timezone.utc).isoformat(), "sources": [{"url": "https://example.test"}], "findings": [{"evidence": "fact"}], "website": "https://example.test"}
    assert submit(client, data).status_code == 422
    data["geo"]["business_id"] = "A"
    assert submit(client, data).status_code == 202
    data["research_requested"] = True
    assert submit(client, data).status_code == 422
    data["research_requested"] = False
    data["context_mode"] = "clinic_enhanced"
    data["geo"]["captured_at"] = "2020-01-01T00:00:00+00:00"
    assert submit(client, data).status_code == 422


def test_copy_revision_preserves_image_and_other_business_cannot_reuse(client):
    data = payload(); data["count"] = 1
    job = submit(client, data).json()["job_id"]
    run_worker()
    candidate = client.get(f"/api/v1/generation-jobs/{job}").json()["candidates"][0]
    data.update(original={"job_id": job, "candidate_id": candidate["id"]}, revision_mode="copy")
    revision = submit(client, data).json()["job_id"]
    run_worker()
    result = client.get(f"/api/v1/generation-jobs/{revision}").json()
    assert result["candidates"][0]["media_sha256"] == candidate["media_sha256"]
    data["business_id"] = "B"
    assert submit(client, data).status_code == 403


def test_generic_agent_never_reads_hygaar_repo(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "AGENTS.md").write_text("Hygaar secret product positioning")
    agent = Agent(BusinessProfile(name="Bakery", sector="bakery"), {}, AgentSettings(data_dir=tmp_path / "own", context_repo=str(repo)))
    assert "Hygaar" not in agent._load_strategy_context().for_prompt()


def test_image_revision_preserves_customer_full_caption(client):
    data = payload(); data["count"] = 1
    job = submit(client, data).json()["job_id"]
    run_worker()
    original = client.get(f"/api/v1/generation-jobs/{job}").json()["candidates"][0]
    text = "Customer opening\n\nCustomer body\n\n#Care"
    data.update(original={"job_id": job, "candidate_id": original["id"]}, revision_mode="image")
    data["public_facts"]["current_post"] = {"topic": "Care", "hook": "", "body": text, "hashtags": [], "cta": ""}
    revision = submit(client, data).json()["job_id"]
    run_worker()
    result = client.get(f"/api/v1/generation-jobs/{revision}").json()
    assert result["state"] == "completed"
    post = result["candidates"][0]["post"]
    assert post["body"] == text
    assert post["hook"] == ""
    assert post["hashtags"] == []
    assert post["link"] is None


def test_three_inputs_reach_copy_and_image_planning(client):
    data = payload(); data.update(context_mode="clinic_enhanced", count=1)
    data["geo"] = {"business_id": "A", "captured_at": datetime.now(timezone.utc).isoformat(),
        "website": "https://example.test", "audit_id": "12", "sources": [{"url": "https://example.test"}],
        "findings": [{"check_id": "hours", "evidence": {"missing": "opening hours"}}]}
    data["research"] = {"business_id": "A", "captured_at": datetime.now(timezone.utc).isoformat(),
        "sources": [{"url": "https://research.example.test"}], "findings": [{"summary": "Local audience questions about clinic opening hours"}]}
    job = submit(client, data).json()["job_id"]
    prompts = run_worker()
    result = client.get(f"/api/v1/generation-jobs/{job}").json()
    assert result["state"] == "completed"
    assert result["evidence"]["geo"]["audit_id"] == "12"
    assert "opening hours" in prompts[0] and "research.example.test" in prompts[1]
    assert result["warnings"] == []


def test_no_logo_inherits_nothing_and_research_cache_is_business_scoped(client):
    data = payload("B"); data["count"] = 1
    job = submit(client, data).json()["job_id"]
    prompts = run_worker()
    result = client.get(f"/api/v1/generation-jobs/{job}").json()
    candidate = result["candidates"][0]
    raw = client.get(f"/api/v1/generation-jobs/{job}/assets/{candidate['id']}").content
    assert Image.open(io.BytesIO(raw)).getpixel((115, 115))[:3] == (0, 1, 255)
    assert "Bakery" in "\n".join(prompts) and "Dental" not in "\n".join(prompts)
    assert "No business logo is supplied" in "\n".join(prompts)
    assert "black box" in "\n".join(prompts)
    with patch.object(worker, "research_business", return_value={"sources": []}) as search:
        for business in ("A", "A", "B"):
            worker.cached_research({"owner": "same-client"}, GenerationRequest.model_validate(payload(business)), {})
    assert search.call_count == 2


@pytest.mark.parametrize("with_logo", [False, True])
def test_final_provider_prompt_and_single_overlay(client, with_logo):
    # Exercise the real media wrapper, not only the worker's mocked entrypoint.
    data = payload(logo=with_logo); data["count"] = 1
    job = submit(client, data).json()["job_id"]
    raw = io.BytesIO()
    Image.new("RGB", (128, 128), (0, 1, 255)).save(raw, "PNG")
    response = Mock()
    response.candidates = [Mock(content=Mock(parts=[Mock(inline_data=Mock(data=raw.getvalue(), mime_type="image/png"))]))]
    generate, _, _ = providers()
    with patch.object(worker.LLMClient, "generate_json", side_effect=generate), patch("google.genai.Client") as sdk:
        sdk.return_value.models.generate_content.return_value = response
        worker.process(store.claim())
    contents = sdk.return_value.models.generate_content.call_args.kwargs["contents"][0]
    assert "Leave clean corner" not in contents
    assert "the provided brand logo" not in contents
    assert "without empty corner boxes or reserved logo areas" in contents
    assert ("No business logo is supplied" in contents) is (not with_logo)
    result = client.get(f"/api/v1/generation-jobs/{job}").json()
    assert result["state"] == "completed"
    candidate = result["candidates"][0]
    asset = client.get(f"/api/v1/generation-jobs/{job}/assets/{candidate['id']}").content
    with Image.open(io.BytesIO(asset)) as image:
        assert image.getpixel((115, 115))[:3] == ((255, 0, 0) if with_logo else (0, 1, 255))
        assert image.getpixel((10, 10))[:3] == (0, 1, 255)


def test_lost_worker_is_not_replayed(client):
    job = submit(client, payload()).json()["job_id"]
    assert store.claim()["id"] == job
    with store.database() as db:
        db.execute("UPDATE jobs SET updated=0 WHERE id=?", (job,))
    assert store.claim() is None
    assert client.get(f"/api/v1/generation-jobs/{job}").json()["state"] == "needs_attention"
    with pytest.raises(store.LeaseLost):
        store.save(job, {"candidates": []})


def enable_org_registration(monkeypatch):
    from pathlib import Path
    import os
    path = Path(os.environ['REACHLY_GENERATION_CONFIG'])
    data = json.loads(path.read_text())
    data['clients']['clinic-service']['organisation_provisioning'] = True
    path.write_text(json.dumps(data))


def test_organisation_registration_requires_service_capability(client, monkeypatch):
    path = '/api/v1/generation-jobs/organisations'
    org = {'organisation_id': 'ORG-' + 'A' * 16}
    assert client.post(path, json=org).status_code == 403
    enable_org_registration(monkeypatch)
    assert client.post(path, json=org, headers={'Authorization': 'Bearer wrong'}).status_code == 401
    assert client.post(path, json=org, headers={'X-Reachly-Client': 'other-service', 'Authorization': 'Bearer fictional-other-secret'}).status_code == 403
    for invalid in ({}, {'organisation_id': 'wrong'}, {**org, 'provider': 'other'}, []):
        assert client.post(path, json=invalid).status_code == 422
    assert client.post(path, content=b'x' * 4097).status_code == 413
    for _ in range(2):
        assert client.post(path, json=org).json() == {**org, 'state': 'registered'}
    assert store.organisation_registered('clinic-service', org['organisation_id'])
    assert not store.organisation_registered('other-service', org['organisation_id'])
    with store.database() as db:
        assert db.execute('SELECT COUNT(*) FROM generation_organisations').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 0


def test_registered_org_allows_new_clinics_and_preserves_binding(client, monkeypatch):
    enable_org_registration(monkeypatch)
    org = 'ORG-' + 'A' * 16
    other = 'ORG-' + 'B' * 16
    data = payload('HYC-' + 'A' * 16)
    data.update(organisation_id=org, count=2, creative_mode='daily_alternatives', topic='Routine checkups')
    assert submit(client, data).status_code == 403
    assert client.post('/api/v1/generation-jobs/organisations', json={'organisation_id': org}).status_code == 200
    key = str(uuid.uuid4())
    first = submit(client, data, key)
    assert first.status_code == 202
    assert submit(client, data, key).json()['job_id'] == first.json()['job_id']
    # A second clinic needs no separate operator configuration.
    assert submit(client, {**data, 'business_id': 'HYC-' + 'B' * 16}).status_code == 202
    assert client.post('/api/v1/generation-jobs/organisations', json={'organisation_id': other}).status_code == 200
    assert submit(client, {**data, 'organisation_id': other}).status_code == 403
    assert submit(client, {**data, 'business_id': 'not-a-clinic'}).status_code == 403
    run_worker()
    job = first.json()['job_id']
    result = client.get(f'/api/v1/generation-jobs/{job}').json()
    assert result['state'] == 'completed'
    asset = f"/api/v1/generation-jobs/{job}/assets/{result['candidates'][0]['id']}"
    assert client.get(asset).status_code == 200
    headers = {'X-Reachly-Client': 'other-service', 'Authorization': 'Bearer fictional-other-secret'}
    assert client.get(f'/api/v1/generation-jobs/{job}', headers=headers).status_code == 404
    assert client.get(asset, headers=headers).status_code == 404
    # Disabling the capability revokes dynamically registered scopes.
    from pathlib import Path
    import os
    path = Path(os.environ['REACHLY_GENERATION_CONFIG'])
    config = json.loads(path.read_text())
    config['clients']['clinic-service']['organisation_provisioning'] = False
    path.write_text(json.dumps(config))
    assert client.get(asset).status_code == 404
    assert submit(client, data).status_code == 403


def test_legacy_inflight_digest_unchanged_after_contract_upgrade(client):
    data = payload()
    legacy = GenerationRequest.model_validate(data).model_dump()
    legacy.pop('organisation_id')
    key = str(uuid.uuid4())
    old = store.submit('clinic-service', key, legacy, 'shared')
    assert submit(client, data, key).json()['job_id'] == old['id']
