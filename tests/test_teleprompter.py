from copy import deepcopy
import json
from unittest.mock import Mock, patch
import pytest
from reachly import generation_store as store, generation_worker as worker
from reachly.generation_contract import GenerationRequest
from reachly.teleprompter import ScriptValidationError, generate_script, script_schema, validate_script
from tests.test_generation_api import client, payload, submit


def script():
    return {"title": "Preparing for your appointment", "sources": ["services"], "segments": [
        {"text": " ".join(["appointment"] * 45), "cue": "warm", "pause_seconds": 1} for _ in range(3)]}


def request():
    data = payload()
    data.update(schema_version=3, operation="teleprompter_script", count=1,
                script_options={"source": "surprise", "target_seconds": 75})
    return data


def test_script_job_is_text_only_and_keeps_scope(client):
    response = submit(client, request())
    assert response.status_code == 202
    job = response.json()["job_id"]
    with patch.object(worker.LLMClient, "generate_json", return_value=script()) as llm, \
            patch.object(worker, "generate_image_gemini") as images, patch.object(worker, "logo_file") as logos:
        worker.process(store.claim())
    result = client.get(f"/api/v1/generation-jobs/{job}").json()
    assert result["state"] == "completed"
    assert result["operation"] == "teleprompter_script"
    assert result["script"]["estimated_seconds"] == 67
    assert result["candidates"] == []
    assert result["business_id"] == request()["business_id"]
    assert llm.call_count == 1
    images.assert_not_called()
    logos.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"schema_version": 2}, {"count": 2}, {"script_options": None},
    {"operation": "posts"}, {"script_options": {"source": "saved_topic", "topic": ""}},
    {"script_options": {"source": "surprise", "target_seconds": 120}},
])
def test_bad_contract_rejected_before_provider(client, changes):
    data = request(); data.update(changes)
    assert submit(client, data).status_code == 422


@pytest.mark.parametrize("field,value", [("cue", "invented"), ("pause_seconds", True), ("pause_seconds", 4), ("text", "[speak] hello")])
def test_bad_segment_rejected(field, value):
    data = script(); data["segments"][0][field] = value
    with pytest.raises(ValueError):
        validate_script(data, {"services"}, 75)


def test_bad_sources_and_duration_rejected():
    data = script(); data["sources"] = ["made_up_award"]
    with pytest.raises(ValueError):
        validate_script(data, {"services"}, 75)
    data = script()
    for s in data["segments"]:
        s["text"] = "Too short"
    with pytest.raises(ValueError):
        validate_script(data, {"services"}, 75)


def test_additive_contract_preserves_v1_v2_replay_digests():
    for version in (1, 2):
        data = payload(); data["schema_version"] = version
        encoded = GenerationRequest.model_validate(data).model_dump()
        assert "script_options" not in encoded
        if version == 1:
            assert "operation" not in encoded


def test_invalid_provider_script_fails_without_fake_fallback(client):
    job = submit(client, request()).json()["job_id"]
    data = deepcopy(script()); data["sources"] = ["another_clinic"]
    with patch.object(worker.LLMClient, "generate_json", return_value=data):
        worker.process(store.claim())
    assert client.get(f"/api/v1/generation-jobs/{job}").json()["state"] == "failed"


@pytest.mark.parametrize("value,code", [
    (None, "script_invalid_structure"),
    ({**script(), "word_count": 135}, "script_invalid_structure"),
    ({**script(), "title": ""}, "script_invalid_title"),
    ({**script(), "segments": []}, "script_invalid_segments"),
    ({**script(), "sources": ["private-provider-output"]}, "script_invalid_sources"),
])
def test_safe_failure_codes_persist_and_no_raw_output_leaks(client, caplog, value, code):
    job = submit(client, request()).json()["job_id"]
    with patch.object(worker.LLMClient, "generate_json", return_value=value) as llm:
        worker.process(store.claim())
    response = client.get(f"/api/v1/generation-jobs/{job}")
    assert response.status_code == 200  # Transport success is not generation success.
    result = response.json()
    assert result["state"] == "failed"
    assert result["error_code"] == code
    assert result["failed_stage"] == "writing_script"
    assert "script" not in result
    assert "private-provider-output" not in response.text + caplog.text
    assert code in caplog.text
    assert llm.call_count == 1


def test_duration_failure_has_only_derived_counts(client, caplog):
    value = script()
    for segment in value["segments"]:
        segment["text"] = "too short"
    job = submit(client, request()).json()["job_id"]
    with patch.object(worker.LLMClient, "generate_json", return_value=value):
        worker.process(store.claim())
    result = client.get(f"/api/v1/generation-jobs/{job}").json()
    assert result["error_code"] == "script_duration_out_of_range"
    assert result["error_metrics"] == {"word_count": 6, "estimated_seconds": 6, "target_seconds": 75}
    assert "too short" not in caplog.text


@pytest.mark.parametrize("error,state,code", [
    (json.JSONDecodeError("private-provider-output", "private-provider-output", 0), "failed", "script_invalid_json"),
    (RuntimeError("private-provider-output"), "needs_attention", "script_provider_error"),
    (ValueError("private-provider-output"), "failed", "script_provider_error"),
])
def test_provider_errors_are_safe_without_retries(client, caplog, error, state, code):
    job = submit(client, request()).json()["job_id"]
    with patch.object(worker.LLMClient, "generate_json", side_effect=error) as llm:
        worker.process(store.claim())
    response = client.get(f"/api/v1/generation-jobs/{job}")
    assert response.json()["state"] == state
    assert response.json()["error_code"] == code
    assert "private-provider-output" not in response.text + caplog.text
    assert llm.call_count == 1


@pytest.mark.parametrize("target,words", [(60, 113), (75, 145), (90, 176)])
def test_schema_and_timing_budget_are_explicit(target, words):
    data = request(); data["script_options"]["target_seconds"] = target
    value = script()
    value["segments"] = [{"text": " ".join(["appointment"] * n), "cue": "warm", "pause_seconds": 2}
                         for n in (words // 3, words // 3, words - 2 * (words // 3))]
    llm = Mock(); llm.generate_json.return_value = value
    result = generate_script(llm, GenerationRequest.model_validate(data), {})
    assert result["estimated_seconds"] == target
    assert f"approximately {words} spoken words" in llm.generate_json.call_args.args[0]
    schema = llm.generate_json.call_args.kwargs["response_schema"]
    assert schema["properties"]["sources"]["items"]["enum"] == ["services"]
    assert llm.generate_json.call_count == 1


def test_missing_public_facts_rejected_before_provider():
    data = request(); data["public_facts"] = {"warnings": ["Not evidence"], "recent_scripts": ["Old topic"]}
    llm = Mock()
    with pytest.raises(ScriptValidationError, match="script_missing_facts"):
        generate_script(llm, GenerationRequest.model_validate(data), {})
    llm.generate_json.assert_not_called()


def test_gemini_structured_output_is_opt_in():
    from reachly.llm import LLMClient
    llm = LLMClient("gemini", gemini_api_key="fictional-key")
    with patch("google.genai.Client") as sdk:
        sdk.return_value.models.generate_content.return_value.text = json.dumps(script())
        result = llm.generate_json("System", "Prompt", response_schema=script_schema({"services"}))
        config = sdk.return_value.models.generate_content.call_args.kwargs["config"]
        assert result == script()
        assert config.response_mime_type == "application/json"
        assert config.response_json_schema["properties"]["sources"]["items"]["enum"] == ["services"]
        llm.generate_json("Existing caller", "Prompt")
        config = sdk.return_value.models.generate_content.call_args.kwargs["config"]
        assert config.response_mime_type is None
        assert config.response_schema is None
        assert config.response_json_schema is None


def test_gemini_sdk_serializes_script_schema_on_the_wire():
    import httpx
    from google import genai
    from google.genai import types
    from reachly.llm import LLMClient

    def respond(http_request):
        body = json.loads(http_request.content)
        config = body["generationConfig"]
        assert config["responseMimeType"] == "application/json"
        schema = config["responseJsonSchema"]
        assert schema["properties"]["sources"]["items"]["enum"] == ["services"]
        assert schema["properties"]["segments"]["minItems"] == 3
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [
            {"text": json.dumps(script())}]}, "finishReason": "STOP"}]})

    with genai.Client(api_key="fictional-key", http_options=types.HttpOptions(
            client_args={"transport": httpx.MockTransport(respond)})) as sdk:
        with patch("google.genai.Client", return_value=sdk):
            value = generate_script(LLMClient("gemini"), GenerationRequest.model_validate(request()), {})
    assert value["word_count"] == 135


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_other_providers_keep_existing_dispatch_and_local_validation(provider):
    from reachly.llm import LLMClient
    llm = LLMClient(provider)
    with patch.object(llm, "_" + provider, return_value=json.dumps(script())) as call:
        result = generate_script(llm, GenerationRequest.model_validate(request()), {})
    assert result["word_count"] == 135
    assert call.call_count == 1
