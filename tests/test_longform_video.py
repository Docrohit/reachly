from unittest.mock import patch

from reachly.agent import Agent, AgentSettings
from reachly.longform_video import (
    ClipQualityReport,
    LongFormManualBrief,
    LongFormPlan,
    _card_count,
    _retry_prompt,
)
from reachly.models import (
    BusinessProfile,
    GeneratedMedia,
    GeneratedPost,
    Platform,
    PlatformCredentials,
    PlatformMode,
    PostResult,
)


def test_longform_card_count_stays_between_four_and_six():
    assert _card_count(60, 18) == 4
    assert _card_count(90, 18) == 5
    assert _card_count(120, 18) == 6


def test_longform_title_uses_fallback_when_auto_title_scores_low():
    plan = LongFormPlan(
        theme="moat",
        title="A generic video",
        fallback_title="Why Hygaar beats building the stack in-house",
        title_alignment_score=4,
        goal_category="prove why using Hygaar is better than building in-house",
        hook="Hook",
        payoff="Payoff",
        script="Script",
        linkedin_caption="Caption",
        youtube_description="Description",
    )

    assert plan.title_for_use(manual_title=False, threshold=7) == plan.fallback_title
    assert plan.title_for_use(manual_title=True, threshold=7) == plan.title


def test_longform_retry_prompt_uses_qc_issues():
    quality = ClipQualityReport(
        has_hallucinations=True,
        hallucination_severity="moderate",
        hallucination_percentage=35,
        issues_detected=[{"description": "hands are warped near product close-up"}],
    )

    prompt = _retry_prompt("Original clean ecommerce scene.", quality, retry_index=1)

    assert "hands are warped" in prompt
    assert "Correction pass 1" in prompt
    assert "no readable text" in prompt


def test_agent_longform_slot_publishes_only_linkedin_and_youtube(tmp_path):
    agent = Agent(
        BusinessProfile(name="Hygaar"),
        {
            Platform.linkedin: PlatformCredentials(
                platform=Platform.linkedin,
                mode=PlatformMode.api,
                api_token="linkedin-token",
            ),
            Platform.twitter: PlatformCredentials(
                platform=Platform.twitter,
                mode=PlatformMode.api,
                api_token="twitter-token",
            ),
            Platform.youtube: PlatformCredentials(
                platform=Platform.youtube,
                mode=PlatformMode.api,
                api_token="youtube-token",
            ),
        },
        AgentSettings(data_dir=tmp_path, dry_run=False),
    )
    post = GeneratedPost(
        theme="moat",
        hook="Why Hygaar beats the in-house build",
        body="Caption",
        media=GeneratedMedia(kind="video", local_path=str(tmp_path / "video.mp4")),
    )
    (tmp_path / "video.mp4").write_bytes(b"video")

    with patch.object(agent, "build_longform_video", return_value=post):
        with patch.object(agent, "_publish") as publish:
            publish.return_value = {
                Platform.linkedin: PostResult(platform=Platform.linkedin, ok=True),
                Platform.youtube: PostResult(platform=Platform.youtube, ok=True),
            }
            results = agent.run_longform_video_slot(
                manual=LongFormManualBrief(title="Manual title")
            )

    assert set(results) == {Platform.linkedin, Platform.youtube}
    assert publish.call_args.kwargs["platforms"] == [Platform.linkedin, Platform.youtube]
    agent.close()
