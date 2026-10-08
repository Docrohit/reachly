import base64
import io
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
from reachly.config import AgentConfig
from reachly.agent import Agent, AgentSettings, VideoCreativeContext
from reachly.models import BusinessProfile, GeneratedPost
from reachly.longform_video import _fallback_plan_data, LongFormManualBrief, _fallback_script
from reachly.dashboard import app as dashboard


def test_environment_logo_requires_matching_business_owner(tmp_path):
    values = {"DATA_DIR": str(tmp_path), "BUSINESS_NAME": "Bakery", "BRAND_LOGO_PATH": "/not-read/hygaar.png"}
    assert AgentConfig(values).brand_logo_path is None
    assert AgentConfig({**values, "BRAND_OWNER": "Hygaar"}).brand_logo_path is None
    assert AgentConfig({**values, "BRAND_OWNER": "Bakery"}).brand_logo_path == values["BRAND_LOGO_PATH"]


def test_standalone_brand_upload_drives_agent_without_product_context(tmp_path):
    previous = dashboard._cfg
    cfg = AgentConfig({"DATA_DIR": str(tmp_path), "BUSINESS_NAME": "Bakery", "BUSINESS_SECTOR": "Bakery", "REACHLY_DASHBOARD_TOKEN": ""})
    dashboard._cfg = cfg
    (tmp_path / "knowledge_bank.md").write_text("Hygaar ecommerce positioning must not be read.")
    raw = io.BytesIO(); Image.new("RGB", (24, 24), "red").save(raw, "PNG")
    try:
        client = TestClient(dashboard.create_app())
        response = client.post("/save", data={"goals": "Explain our bakery services", "brand_colors": "#123456", "brand_theme": "Natural warm light", "brand_logo_base64": base64.b64encode(raw.getvalue()).decode()})
        assert response.status_code == 200
        agent = Agent.from_config(cfg)
        assert agent.business.brand_colors == ["#123456"]
        assert agent.business.brand_theme == "Natural warm light"
        assert Path(agent.settings.brand_logo_path).is_file()
        assert "bakery services" in agent._strategy.for_prompt()
        assert "Hygaar" not in agent._strategy.for_prompt()
        agent.close()
    finally:
        dashboard._cfg = previous


def test_clinic_video_helpers_do_not_invent_hygaar_or_ecommerce(tmp_path):
    agent = Agent(BusinessProfile(name="Fictional Clinic", sector="Dentistry"), {}, AgentSettings(data_dir=tmp_path))
    post = GeneratedPost(theme="Clinic hours", hook="Meet our clinic", body="Ask us about available services.")
    prompt = agent._video_prompt_for_post(post, VideoCreativeContext(strategy="fresh", reference_images=[], source_posts=[]))
    narration = agent._video_voiceover_script(post, expressive=True)
    fallback = _fallback_plan_data(post, LongFormManualBrief(), word_target=180)
    for text in (prompt, narration, str(fallback), _fallback_script(post)):
        assert "Hygaar" not in text and "Haigaar" not in text
        assert "ecommerce" not in text and "catalogue" not in text
    agent.close()
