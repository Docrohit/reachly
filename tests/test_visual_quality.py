import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from PIL import Image
from reachly import visual
from reachly.media import generate_image_gemini
from reachly.models import BusinessProfile, GeneratedPost, GeneratedMedia
from reachly.generation_contract import GenerationRequest


def png(color="red", size=(128, 128)):
    buf = io.BytesIO(); Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def plan():
    return dict(subject="Bread on a table", composition="One loaf in centre", lighting="Natural",
                palette="Warm brown", reference_usage="Preserve product", avoid="Invented claims")


def review(score=5):
    return visual.Review(relevance=score, brand=5, reference_fidelity=5, visual_integrity=5, claim_safety=5, issues=[])


def test_references_reject_urls_corruption_and_oversized_dimensions():
    for bad in ["https://example.test/image.png", base64.b64encode(b"not pixels").decode(), base64.b64encode(png(size=(4097, 32))).decode()]:
        with pytest.raises(ValueError):
            visual.ReferenceImage(role="product", image_base64=bad)
    assert visual.ReferenceImage(role="style", image_base64=base64.b64encode(png()).decode()).role == "style"


def test_gemini_receives_pixels_and_exact_shape_and_size(tmp_path):
    response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(inline_data=SimpleNamespace(data=png(size=(160, 200)), mime_type="image/png"))]))])
    with patch("google.genai.Client") as client:
        client.return_value.models.generate_content.return_value = response
        result = generate_image_gemini("Show product", api_key="synthetic-secret", out_dir=tmp_path,
            aspect_ratio="4:5", image_size="2K", reference_images=[{"role": "product", "data": png()}])
        call = client.return_value.models.generate_content.call_args.kwargs
    assert call["config"].image_config.aspect_ratio == "4:5"
    assert call["config"].image_config.image_size == "2K"
    assert call["contents"][2].inline_data.data == png()
    assert result.prompt == call["contents"][0]
    assert "synthetic-secret" not in result.model_dump_json()


def test_legacy_model_does_not_silently_ignore_resolution(tmp_path):
    with patch("google.genai.Client") as client, pytest.raises(ValueError):
        generate_image_gemini("Product", api_key="synthetic", model="gemini-2.5-flash-image", out_dir=tmp_path, image_size="4K")
    client.return_value.models.generate_content.assert_not_called()


@pytest.mark.parametrize("score", [5, 1])
def test_visual_plan_edit_feedback_audit_and_quality_gate(tmp_path, score):
    original = tmp_path / "original.png"; original.write_bytes(png("blue"))
    refs = [visual.ReferenceImage(role="product", label="Our bread", image_base64=base64.b64encode(png()).decode())]
    llm = Mock(provider="gemini", model="test-copy")
    llm.generate_json.return_value = plan()
    recorded = visual.RecordedLLM(llm, tmp_path / "text-prompts.json")
    calls = []
    def generate(prompt, **kwargs):
        calls.append((prompt, kwargs)); path = tmp_path / "provider.png"; path.write_bytes(png())
        return GeneratedMedia(kind="image", local_path=str(path))
    args = dict(post=GeneratedPost(theme="Bread", hook="A loaf", body="Baked daily"), business=BusinessProfile(name="Bakery"),
        context={"audit": "Bread service", "saas2point0": "Local audience"}, llm=recorded,
        provider={"gemini_api_key": "synthetic-secret", "image_model": "test-image"}, folder=tmp_path,
        candidate_id="candidate", references=refs, original_path=original, feedback="Change background to blue", generator=generate)
    with patch.object(visual, "review_visual", return_value=review(score)):
        if score == 1:
            with pytest.raises(ValueError): visual.create_visual(**args)
        else:
            assert Path(visual.create_visual(**args).local_path).exists()
    audit = json.loads((tmp_path / "candidate.audit.json").read_text())
    assert len(calls) == 1  # No automatic charged regeneration after review failure.
    assert calls[0][1]["reference_images"][0]["data"] == original.read_bytes()
    assert calls[0][1]["reference_images"][0]["role"] == "original"
    assert "Change background to blue" in calls[0][0]
    assert audit["quality_review"]["passed"] is (score == 5)
    assert audit["state"] == ("completed" if score == 5 else "failed")
    assert audit["visual_plan"]["subject"] == "Bread on a table"
    assert audit["references"][1]["role"] == "product"
    assert "synthetic-secret" not in json.dumps(audit)
    trace = json.loads((tmp_path / "text-prompts.json").read_text())
    assert trace["calls"][0]["system"] == visual.PLAN_SYSTEM


def test_review_failure_retains_provider_prompt_and_does_not_return_image(tmp_path):
    llm = Mock(); llm.generate_json.return_value = plan()
    def generate(prompt, **kwargs):
        p = tmp_path / "provider.png"; p.write_bytes(png())
        return GeneratedMedia(kind="image", local_path=str(p))
    with patch.object(visual, "review_visual", side_effect=RuntimeError("synthetic secret error")), pytest.raises(RuntimeError):
        visual.create_visual(post=GeneratedPost(theme="Bread", hook="Bread", body="Bread"), business=BusinessProfile(name="Bakery"),
            context={}, llm=llm, provider={"gemini_api_key": "synthetic", "image_model": "test"}, folder=tmp_path,
            candidate_id="candidate", generator=generate)
    audit = json.loads((tmp_path / "candidate.audit.json").read_text())
    assert audit["state"] == "failed" and audit["final_image_prompt"]
    assert audit["review_call"]["system"] == visual.REVIEW_SYSTEM
    assert "synthetic secret error" not in json.dumps(audit)


def test_layout_keeps_shape_adds_exact_text_and_logo(tmp_path):
    raw = tmp_path / "raw.png"; raw.write_bytes(png("blue", (1000, 1000)))
    logo = tmp_path / "logo.png"; logo.write_bytes(png("red"))
    target = tmp_path / "layout.png"
    visual.compose(raw, target, visual.Layout(headline="Fresh bread", cta="Visit our bakery"), str(logo))
    with Image.open(target) as image:
        assert image.size == (1000, 1000)
        assert image.getpixel((850, 850)) == (255, 0, 0)
        assert image.getpixel((10, 990)) == (255, 255, 255)
        assert image.getpixel((500, 200)) == (0, 0, 255)


def test_visual_fields_version_and_replay_digest_compatibility():
    old = GenerationRequest(business_id="one", business=BusinessProfile(name="Bakery"), source_version="v1")
    assert "visual" not in old.model_dump() and "references" not in old.model_dump()
    with pytest.raises(ValueError):
        old.model_copy(update={"visual": visual.VisualOptions()}).check_scope()
    new = old.model_copy(update={"schema_version": 4, "visual": visual.VisualOptions()})
    new.check_scope()


def test_portrait_4k_dimensions_are_accepted_without_downscaling(tmp_path):
    raw = tmp_path/'4k.png'; raw.write_bytes(png(size=(3072,5504)))
    target = tmp_path/'output.png'
    visual.compose(raw, target, visual.Layout(), None)
    with Image.open(target) as image:
        assert image.size == (3072,5504)


def test_preflight_rejects_unavailable_unicode_font(monkeypatch):
    monkeypatch.delenv('REACHLY_LAYOUT_FONT', raising=False)
    with pytest.raises(ValueError):
        visual.validate_options(visual.VisualOptions(layout=visual.Layout(headline='नमस्ते')), 'test')
