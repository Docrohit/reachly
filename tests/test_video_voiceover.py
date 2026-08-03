from unittest.mock import patch

from reachly.agent import Agent, AgentSettings
from reachly.models import BusinessProfile, GeneratedMedia, GeneratedPost


def _agent(tmp_path, *, api_key="openai-key"):
    return Agent(
        BusinessProfile(name="Hygaar"),
        {},
        AgentSettings(
            data_dir=tmp_path,
            dry_run=True,
            openai_api_key=api_key,
            video_voiceover_enabled=True,
            video_voiceover_provider="openai",
        ),
    )


def _elevenlabs_agent(tmp_path, *, api_key="eleven-key"):
    return Agent(
        BusinessProfile(name="Hygaar"),
        {},
        AgentSettings(
            data_dir=tmp_path,
            dry_run=True,
            elevenlabs_api_key=api_key,
            video_voiceover_enabled=True,
            video_voiceover_provider="elevenlabs",
            elevenlabs_model="eleven_v3",
            spoken_brand_name="Haigaar",
        ),
    )


def test_agent_adds_voiceover_when_generated_video_is_silent(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    voiced = tmp_path / "video_voiced.mp4"

    agent = _agent(tmp_path)
    post = GeneratedPost(
        theme="catalog ops",
        hook="Make catalog content scalable",
        body="Hygaar turns product references into reusable campaign media.",
    )
    media = GeneratedMedia(kind="video", local_path=str(video))

    with (
        patch("reachly.agent.video_has_audio", return_value=False),
        patch(
            "reachly.agent.add_openai_voiceover",
            return_value=GeneratedMedia(kind="video", local_path=str(voiced)),
        ) as add_voiceover,
    ):
        result = agent._add_video_voiceover_if_needed(post, media)

    assert result.local_path == str(voiced)
    assert add_voiceover.call_args.kwargs["api_key"] == "openai-key"
    agent.close()


def test_agent_adds_elevenlabs_voiceover_when_generated_video_is_silent(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    voiced = tmp_path / "video_elevenlabs.mp4"

    agent = _elevenlabs_agent(tmp_path)
    post = GeneratedPost(
        theme="beauty and home ecommerce",
        hook="Make catalog content scalable",
        body="Hygaar turns product references into reusable campaign media.",
    )
    media = GeneratedMedia(kind="video", local_path=str(video))

    with (
        patch("reachly.agent.video_has_audio", return_value=False),
        patch(
            "reachly.agent.add_elevenlabs_voiceover",
            return_value=GeneratedMedia(kind="video", local_path=str(voiced)),
        ) as add_voiceover,
    ):
        result = agent._add_video_voiceover_if_needed(post, media)

    assert result.local_path == str(voiced)
    assert add_voiceover.call_args.kwargs["api_key"] == "eleven-key"
    assert add_voiceover.call_args.kwargs["model_id"] == "eleven_v3"
    script = add_voiceover.call_args.args[1]
    assert "Haigaar turns" in script
    assert "product page visuals" in script
    assert "SKUs" not in script
    assert "[confident" in script
    agent.close()


def test_agent_keeps_video_when_audio_already_exists(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")

    agent = _agent(tmp_path)
    post = GeneratedPost(theme="catalog ops", hook="Hook", body="Body")
    media = GeneratedMedia(kind="video", local_path=str(video))

    with (
        patch("reachly.agent.video_has_audio", return_value=True),
        patch("reachly.agent.add_openai_voiceover") as add_voiceover,
    ):
        result = agent._add_video_voiceover_if_needed(post, media)

    assert result is media
    add_voiceover.assert_not_called()
    agent.close()


def test_agent_keeps_silent_video_when_openai_key_is_missing(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")

    agent = _agent(tmp_path, api_key=None)
    post = GeneratedPost(theme="catalog ops", hook="Hook", body="Body")
    media = GeneratedMedia(kind="video", local_path=str(video))

    with patch("reachly.agent.add_openai_voiceover") as add_voiceover:
        result = agent._add_video_voiceover_if_needed(post, media)

    assert result is media
    add_voiceover.assert_not_called()
    agent.close()


def test_voiceover_script_is_short_and_dedupes_hook(tmp_path):
    agent = _agent(tmp_path)
    post = GeneratedPost(
        theme="beauty and home ecommerce",
        hook="A long social hook that should not become the entire narration",
        body="Catalog speed matters. " + " ".join(["word"] * 120),
    )

    script = agent._video_voiceover_script(post, max_words=64, expressive=True)

    assert "For beauty and home brands" in script
    assert "Haigaar turns" in script
    assert "entire narration" not in script
    assert "product page visuals" in script
    assert "PDP" not in script
    assert "[confident" in script
    agent.close()
