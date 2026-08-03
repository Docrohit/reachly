from unittest.mock import patch

from reachly.config import AgentConfig
from reachly.media import SeedanceClient, resolve_seedance_model
from reachly.models import GeneratedMedia, Platform, PostResult
from reachly.runner import _results_exit_code, _seedance_account_check, _video_preflight


class Response:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def test_seedance_25_model_resolves_to_modelark_id():
    assert resolve_seedance_model("seedance_2_5") == "dreamina-seedance-2-5-260628"


def test_seedance_client_create_task_uses_backend_payload_shape():
    client = SeedanceClient("seedance-key", poll_interval=0)

    with patch(
        "reachly.media.requests.post",
        return_value=Response({"id": "task-1", "status": "queued"}, status_code=201),
    ) as post:
        task_id = client._create_task(
            "seedance_2_5",
            "Make a premium product video",
            ratio="portrait",
            duration=30,
            generate_audio=True,
            watermark=False,
        )

    assert task_id == "task-1"
    payload = post.call_args.kwargs["json"]
    assert payload["model"] == "dreamina-seedance-2-5-260628"
    assert payload["content"] == [{"type": "text", "text": "Make a premium product video"}]
    assert payload["ratio"] == "9:16"
    assert payload["duration"] == 30
    assert payload["generate_audio"] is True
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer seedance-key"


def test_seedance_client_create_task_includes_model_limited_reference_images():
    client = SeedanceClient("seedance-key", poll_interval=0)
    refs = [
        {"url": f"https://cdn.example/ref-{idx}.png", "role": "reference_image"}
        for idx in range(60)
    ]

    with patch(
        "reachly.media.requests.post",
        return_value=Response({"id": "task-1", "status": "queued"}, status_code=201),
    ) as post:
        client._create_task(
            "seedance_2_5",
            "Make a premium product video",
            ratio="9:16",
            duration=30,
            generate_audio=True,
            watermark=False,
            reference_images=[{"url": "https://cdn.example/logo.png", "role": "brand_logo"}]
            + refs,
        )

    content = post.call_args.kwargs["json"]["content"]
    assert len(content) == 31
    assert content[0] == {"type": "text", "text": "Make a premium product video"}
    assert content[1]["role"] == "reference_image"
    assert content[1]["image_url"]["url"] == "https://cdn.example/logo.png"


def test_seedance_20_reference_images_are_capped_lower_than_25():
    client = SeedanceClient("seedance-key", poll_interval=0)
    refs = [f"https://cdn.example/ref-{idx}.png" for idx in range(20)]

    with patch(
        "reachly.media.requests.post",
        return_value=Response({"id": "task-1", "status": "queued"}, status_code=201),
    ) as post:
        client._create_task(
            "seedance_2_0",
            "Make a premium product video",
            ratio="9:16",
            duration=15,
            generate_audio=True,
            watermark=False,
            reference_images=refs,
        )

    assert len(post.call_args.kwargs["json"]["content"]) == 13


def test_seedance_25_uses_native_30_seconds_before_segmenting_fallback():
    client = SeedanceClient("seedance-key", poll_interval=0)

    assert client._clip_durations(
        model_key="seedance_2_5",
        target_duration=30,
        clip_count=0,
        clip_duration=15,
    ) == [30]
    assert client._clip_durations(
        model_key="seedance_2_0",
        target_duration=30,
        clip_count=0,
        clip_duration=15,
    ) == [15, 15]


def test_seedance_client_poll_reads_completed_video_url():
    client = SeedanceClient("seedance-key", poll_interval=0, max_poll_attempts=1)

    with patch(
        "reachly.media.requests.get",
        return_value=Response(
            {"status": "succeeded", "content": {"video_url": "https://cdn.example/video.mp4"}}
        ),
    ):
        assert client._await_video_url("task-1") == "https://cdn.example/video.mp4"


def test_seedance_client_falls_back_to_20_when_25_generation_fails(tmp_path):
    client = SeedanceClient(
        "seedance-key",
        model_key="seedance_2_5",
        fallback_model_key="seedance_2_0",
    )
    fallback_media = GeneratedMedia(kind="video", local_path=str(tmp_path / "fallback.mp4"))

    with patch.object(
        client,
        "_generate_video_for_model",
        side_effect=[RuntimeError("2.5 temporarily unavailable"), fallback_media],
    ) as generate:
        media = client.generate_video("Make a premium product video", tmp_path)

    assert media == fallback_media
    assert generate.call_args_list[0].args[0] == "seedance_2_5"
    assert generate.call_args_list[1].args[0] == "seedance_2_0"


def test_seedance_client_retries_without_audio_on_audio_policy_error(tmp_path):
    client = SeedanceClient(
        "seedance-key",
        model_key="seedance_2_5",
        fallback_model_key="seedance_2_0",
    )
    silent_media = GeneratedMedia(kind="video", local_path=str(tmp_path / "silent.mp4"))

    with patch.object(
        client,
        "_generate_video_with_fallback",
        side_effect=[
            RuntimeError("OutputAudioSensitiveContentDetected.PolicyViolation"),
            silent_media,
        ],
    ) as generate:
        media = client.generate_video("Make a premium product video", tmp_path, generate_audio=True)

    assert media == silent_media
    assert generate.call_args_list[0].kwargs["generate_audio"] is True
    assert generate.call_args_list[1].kwargs["generate_audio"] is False


def test_seedance_config_enables_three_image_two_video_plan_by_default():
    cfg = AgentConfig({"VIDEO_PROVIDER": "seedance", "SEEDANCE_API_KEY": "seedance-key"})

    assert cfg.video_provider == "seedance"
    assert cfg.seedance_model == "seedance_2_5"
    assert cfg.seedance_fallback_model == "seedance_2_0"
    assert cfg.seedance_clip_count == 0
    assert cfg.daily_media_plan == ["image", "image", "image", "video", "video"]


def test_seedance_config_accepts_agent8_modelark_key_aliases():
    assert (
        AgentConfig({"VIDEO_PROVIDER": "seedance", "ARK_API_KEY": "ark-key"}).seedance_api_key
        == "ark-key"
    )
    assert (
        AgentConfig(
            {"VIDEO_PROVIDER": "seedance", "MODELARK_API_KEY": "modelark-key"}
        ).seedance_api_key
        == "modelark-key"
    )


def test_video_preflight_reports_missing_live_seedance_config(capsys):
    cfg = AgentConfig({"VIDEO_PROVIDER": "none", "LINKEDIN_MODE": "browser"})

    code = _video_preflight(cfg)
    output = capsys.readouterr().out

    assert code == 2
    assert "missing SEEDANCE_API_KEY, ARK_API_KEY, or MODELARK_API_KEY" in output
    assert "DRY_RUN must be" in output


def test_video_preflight_passes_for_linkedin_browser_seedance_config(capsys):
    cfg = AgentConfig(
        {
            "VIDEO_PROVIDER": "seedance",
            "SEEDANCE_API_KEY": "seedance-secret-value",
            "SEEDANCE_MODEL": "seedance_2_5",
            "SEEDANCE_FALLBACK_MODEL": "seedance_2_0",
            "DRY_RUN": "no",
            "LINKEDIN_MODE": "browser",
            "LINKEDIN_EMAIL": "person@example.com",
            "LINKEDIN_PASSWORD": "secret",
        }
    )

    code = _video_preflight(cfg)
    output = capsys.readouterr().out

    assert code == 0
    assert "seedance-secret-value" not in output
    assert "ok      seedance_api_key" in output


def test_video_preflight_accepts_persistent_linkedin_session(tmp_path, capsys):
    session_dir = tmp_path / "browser_sessions" / "linkedin" / "Default"
    session_dir.mkdir(parents=True)
    (session_dir / "Preferences").write_text("{}", encoding="utf-8")
    cfg = AgentConfig(
        {
            "DATA_DIR": str(tmp_path),
            "VIDEO_PROVIDER": "seedance",
            "SEEDANCE_API_KEY": "seedance-secret-value",
            "DRY_RUN": "no",
            "LINKEDIN_MODE": "browser",
        }
    )

    code = _video_preflight(cfg)
    output = capsys.readouterr().out

    assert code == 0
    assert "ok      linkedin_login" in output


def test_results_exit_code_fails_when_any_post_result_failed():
    assert _results_exit_code({}) == 0
    assert _results_exit_code({Platform.linkedin: PostResult(platform=Platform.linkedin, ok=True)}) == 0
    assert (
        _results_exit_code(
            {
                Platform.linkedin: PostResult(
                    platform=Platform.linkedin,
                    ok=False,
                    error="Video generation did not produce a video",
                )
            }
        )
        == 2
    )


def test_seedance_account_check_reports_provider_blocks_without_secret(capsys):
    cfg = AgentConfig(
        {
            "VIDEO_PROVIDER": "seedance",
            "SEEDANCE_API_KEY": "seedance-secret-value",
            "SEEDANCE_MODEL": "seedance_2_5",
            "SEEDANCE_FALLBACK_MODEL": "seedance_2_0",
        }
    )

    with patch(
        "reachly.media.requests.post",
        return_value=Response(
            {"code": "ModelNotOpen", "message": "model is not activated"},
            status_code=404,
            text="model is not activated",
        ),
    ):
        code = _seedance_account_check(cfg, duration=4)

    output = capsys.readouterr().out
    assert code == 2
    assert "blocked seedance_2_5" in output
    assert "blocked seedance_2_0" in output
    assert "ModelNotOpen" in output
    assert "seedance-secret-value" not in output
