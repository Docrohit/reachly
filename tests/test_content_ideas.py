from unittest.mock import patch
from reachly import generation_store as store, generation_worker as worker
from tests.test_generation_api import client, payload, submit, providers


def test_ideas_generate_scripts_without_paid_images(client):
    data = payload(); data.update(schema_version=2, operation="ideas", count=3)
    job = submit(client, data).json()["job_id"]
    values = [{"title": f"Topic {i}", "reason": "Useful services", "script": "An editable script.", "sources": ["services"]} for i in range(3)]
    with patch.object(worker.LLMClient, "generate_json", return_value={"ideas": values}), patch.object(worker, "generate_image_gemini") as images:
        worker.process(store.claim())
    result = client.get(f"/api/v1/generation-jobs/{job}").json()
    assert result["state"] == "completed"
    assert result["ideas"] == values
    images.assert_not_called()


def test_ideas_reject_invented_source_fields(client):
    data = payload(); data.update(schema_version=2, operation="ideas", count=3)
    job = submit(client, data).json()["job_id"]
    values = [{"title": f"Topic {i}", "reason": "Claim", "script": "Script", "sources": ["nonexistent_award"]} for i in range(3)]
    with patch.object(worker.LLMClient, "generate_json", return_value={"ideas": values}):
        worker.process(store.claim())
    assert client.get(f"/api/v1/generation-jobs/{job}").json()["state"] == "failed"


def test_v2_brief_reaches_copy_prompt_and_v1_rejects_new_fields(client):
    data = payload(); data.update(schema_version=2, count=1, brief={"setting": "lab", "theme": "community"})
    job = submit(client, data).json()["job_id"]
    generate, image, prompts = providers()
    with patch.object(worker.LLMClient, "generate_json", side_effect=generate), patch.object(worker, "generate_image_gemini", side_effect=image):
        worker.process(store.claim())
    assert client.get(f"/api/v1/generation-jobs/{job}").json()["state"] == "completed"
    assert any('"setting": "lab"' in p for p in prompts)
    data["schema_version"] = 1
    assert submit(client, data).status_code == 422


PERFORMANCE = {"window_days": 90, "measured_posts": 4, "metric": "engagement_rate",
               "top": [{"topic": "Night-time brushing", "hook": "Your toothbrush works the night shift", "narrative": "educational", "score": 0.09}],
               "bottom": [{"topic": "Clinic hours", "hook": "We are open", "narrative": "educational", "score": 0.01}],
               "by_content_type": {"prevention": {"posts": 3, "avg_engagement_rate": 0.07}}, "by_platform": {"instagram": 0.06}}


def test_performance_signals_reach_planning_copy_and_ideas(client):
    data = payload(); data.update(count=1, performance=PERFORMANCE)
    job = submit(client, data).json()["job_id"]
    generate, image, prompts = providers()
    systems = []
    def record(system, prompt):
        systems.append(system)
        return generate(system, prompt)
    with patch.object(worker.LLMClient, "generate_json", side_effect=record), patch.object(worker, "generate_image_gemini", side_effect=image):
        worker.process(store.claim())
    result = client.get(f"/api/v1/generation-jobs/{job}").json()
    assert result["state"] == "completed" and result["performance_used"] == 4
    assert any("performance_signals" in s for s in systems)  # planner directive
    assert all("Your toothbrush works the night shift" in p for p in prompts[:2])  # planning and copy context
    data = payload(); data.update(schema_version=2, operation="ideas", count=3, performance=PERFORMANCE)
    submit(client, data)
    values = [{"title": f"Topic {i}", "reason": "Useful", "script": "Script.", "sources": ["services"]} for i in range(3)]
    with patch.object(worker.LLMClient, "generate_json", return_value={"ideas": values}) as ideas:
        worker.process(store.claim())
    assert "performance_guidance" in ideas.call_args.args[1]


def test_performance_is_optional_bounded_and_preserves_legacy_digest(client):
    from reachly.generation_contract import GenerationRequest
    assert "performance" not in GenerationRequest.model_validate(payload()).model_dump()
    data = payload(); data["performance"] = {**PERFORMANCE, "top": [{"hook": "x"}] * 11}
    assert submit(client, data).status_code == 422
    data["performance"] = {**PERFORMANCE, "unexpected": True}
    assert submit(client, data).status_code == 422


CONTRIBUTION = {"id": "8f0c2a1e-4d3b-4c1a-9e7f-1a2b3c4d5e6f", "title": "Best of Austin family dentist 2025",
                "note": "Readers' choice award, announced November 2025.", "event_date": "2025-11-14",
                "source_url": "https://example.com/best-of-2025"}


def test_focus_contribution_reaches_planning_and_copy(client):
    data = payload(); data.update(count=1, contributions=[{**CONTRIBUTION, "focus": True}])
    job = submit(client, data).json()["job_id"]
    generate, image, prompts = providers()
    systems = []
    def record(system, prompt):
        systems.append(system)
        return generate(system, prompt)
    with patch.object(worker.LLMClient, "generate_json", side_effect=record), patch.object(worker, "generate_image_gemini", side_effect=image):
        worker.process(store.claim())
    result = client.get(f"/api/v1/generation-jobs/{job}").json()
    assert result["state"] == "completed" and result["contributions_used"] == 1
    assert any("marked focus" in s for s in systems)  # planner must centre the requested item
    assert all("Best of Austin family dentist 2025" in p for p in prompts[:2])
    assert all("contribution_guidance" in p for p in prompts[:2])


def test_ideas_and_scripts_may_cite_contributions(client):
    data = payload(); data.update(schema_version=2, operation="ideas", count=3, contributions=[CONTRIBUTION])
    job = submit(client, data).json()["job_id"]
    values = [{"title": f"Topic {i}", "reason": "Award", "script": "Script.", "sources": ["clinic_contributions"]} for i in range(3)]
    with patch.object(worker.LLMClient, "generate_json", return_value={"ideas": values}):
        worker.process(store.claim())
    assert client.get(f"/api/v1/generation-jobs/{job}").json()["state"] == "completed"
    data = payload(); data.update(schema_version=2, operation="ideas", count=3)
    job = submit(client, data).json()["job_id"]
    with patch.object(worker.LLMClient, "generate_json", return_value={"ideas": values}):
        worker.process(store.claim())
    assert client.get(f"/api/v1/generation-jobs/{job}").json()["state"] == "failed"  # absent material cannot be cited


def test_contributions_are_optional_bounded_and_preserve_legacy_digest(client):
    from reachly.generation_contract import GenerationRequest
    assert "contributions" not in GenerationRequest.model_validate(payload()).model_dump()
    for bad in ([{**CONTRIBUTION, "unexpected": True}], [{**CONTRIBUTION, "note": "x" * 2001}],
                [{**CONTRIBUTION, "id": f"c{i}"} for i in range(11)], [CONTRIBUTION, CONTRIBUTION],
                [{**CONTRIBUTION, "focus": True}, {**CONTRIBUTION, "id": "other", "focus": True}],
                [{**CONTRIBUTION, "source_url": "javascript:alert(1)"}], [{**CONTRIBUTION, "event_date": "soon"}]):
        data = payload(); data["contributions"] = bad
        assert submit(client, data).status_code == 422
    data = payload(); data.update(schema_version=2, operation="ideas", count=3, contributions=[{**CONTRIBUTION, "focus": True}])
    assert submit(client, data).status_code == 422  # focus is only meaningful for a requested post
