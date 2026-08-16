"""Narration-led long-form video generation for Reachly.

The pipeline mirrors the proven YouTube Doodle shape: theme/title -> script ->
voiceover -> timed transcript -> visual cards -> silent clips -> QC retries ->
final render. It deliberately sits beside the existing short social video path.
"""
from __future__ import annotations

import json
import logging
import math
import mimetypes
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from google.genai import types

from .llm import LLMClient
from .media import (
    SeedanceClient,
    generate_elevenlabs_speech,
    mux_narration_video,
)
from .models import BusinessProfile, GeneratedMedia, GeneratedPost

logger = logging.getLogger("reachly.longform_video")

LONGFORM_GOALS = [
    "showcase Hygaar's exceptional abilities",
    "showcase Hygaar's moat",
    "prove why using Hygaar is better than building in-house",
    "explain a Hygaar feature",
]


@dataclass
class LongFormManualBrief:
    topic: Optional[str] = None
    title: Optional[str] = None
    hook: Optional[str] = None
    payoff: Optional[str] = None

    @property
    def has_any(self) -> bool:
        return any([self.topic, self.title, self.hook, self.payoff])


@dataclass
class LongFormPlan:
    theme: str
    title: str
    fallback_title: str
    title_alignment_score: int
    goal_category: str
    hook: str
    payoff: str
    script: str
    linkedin_caption: str
    youtube_description: str
    hashtags: list[str] = field(default_factory=list)
    visual_beats: list[dict] = field(default_factory=list)

    def title_for_use(self, *, manual_title: bool, threshold: int) -> str:
        if manual_title:
            return self.title.strip() or self.fallback_title.strip()
        if self.title_alignment_score < threshold and self.fallback_title.strip():
            return self.fallback_title.strip()
        return self.title.strip() or self.fallback_title.strip()


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class VisualCard:
    index: int
    start: float
    end: float
    transcript: str
    beat: str
    prompt: str

    @property
    def duration(self) -> float:
        return max(4.0, self.end - self.start)


@dataclass
class ClipQualityReport:
    success: bool = True
    has_hallucinations: bool = False
    hallucination_severity: str = "none"
    hallucination_percentage: int = 0
    overall_quality_score: int = 8
    recommended_retry: bool = False
    issues_detected: list[dict] = field(default_factory=list)
    improvement_suggestions: dict = field(default_factory=dict)
    new_prompt: Optional[str] = None
    error: Optional[str] = None
    raw_response: dict = field(default_factory=dict)

    def needs_retry(self) -> bool:
        return bool(self.has_hallucinations or self.recommended_retry)

    def rank_tuple(self) -> tuple[int, int, int]:
        severity_rank = {
            "none": 0,
            "minor": 1,
            "moderate": 2,
            "severe": 3,
        }.get(str(self.hallucination_severity or "none").lower(), 2)
        return (
            int(self.hallucination_percentage or 0),
            severity_rank,
            10 - int(self.overall_quality_score or 0),
        )


@dataclass
class ClipAttempt:
    card_index: int
    attempt_index: int
    prompt: str
    media: Optional[GeneratedMedia]
    quality: ClipQualityReport
    error: Optional[str] = None

    @property
    def usable(self) -> bool:
        return bool(self.media and self.media.local_path and Path(self.media.local_path).is_file())


@dataclass
class LongFormVideoResult:
    post: GeneratedPost
    plan: LongFormPlan
    audio_path: Path
    transcript: list[TranscriptSegment]
    cards: list[VisualCard]
    attempts: list[ClipAttempt]
    selected_attempts: list[ClipAttempt]
    final_media: GeneratedMedia
    manifest_path: Path


@dataclass
class LongFormVideoConfig:
    data_dir: Path
    target_seconds: int = 90
    card_seconds: int = 18
    max_card_retries: int = 2
    title_alignment_threshold: int = 7
    qc_enabled: bool = True
    qc_model: str = "gemini-2.5-flash"
    openai_transcription_model: str = "gpt-4o-transcribe"
    openai_transcription_fallback_model: str = "whisper-1"
    seedance_api_key: Optional[str] = None
    seedance_base_url: str = "https://ark.ap-southeast.bytepluses.com/api/v3"
    seedance_model: str = "seedance_2_5"
    seedance_fallback_model: str = "seedance_2_0"
    seedance_watermark: bool = False
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    elevenlabs_model: str = "eleven_v3"
    elevenlabs_output_format: str = "mp3_44100_128"
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None


class LongFormVideoMaker:
    def __init__(
        self,
        *,
        llm: LLMClient,
        business: BusinessProfile,
        strategy_text: str,
        config: LongFormVideoConfig,
    ):
        self.llm = llm
        self.business = business
        self.strategy_text = strategy_text
        self.config = config
        self.config.data_dir = Path(config.data_dir)

    def make(
        self,
        source_post: GeneratedPost,
        *,
        manual: Optional[LongFormManualBrief] = None,
    ) -> LongFormVideoResult:
        manual = manual or LongFormManualBrief()
        work_dir = self.config.data_dir / "longform_video" / time.strftime("%Y%m%d_%H%M%S")
        media_dir = work_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)

        plan = self._plan_video(source_post, manual=manual)
        title = plan.title_for_use(
            manual_title=bool(manual.title),
            threshold=self.config.title_alignment_threshold,
        )
        plan.title = title

        audio_path = generate_elevenlabs_speech(
            plan.script,
            api_key=self.config.elevenlabs_api_key or "",
            out_dir=media_dir,
            voice_id=self.config.elevenlabs_voice_id,
            model_id=self.config.elevenlabs_model,
            output_format=self.config.elevenlabs_output_format,
        )
        audio_duration = _probe_duration(audio_path)
        transcript = transcribe_audio_openai(
            audio_path,
            api_key=self.config.openai_api_key,
            primary_model=self.config.openai_transcription_model,
            fallback_model=self.config.openai_transcription_fallback_model,
        )
        if not transcript:
            transcript = _estimate_transcript(plan.script, duration=audio_duration)

        cards = self._build_cards(plan, transcript, duration=audio_duration)
        clip_attempts, selected = self._generate_cards(cards, media_dir=media_dir)
        final_media = LongFormRenderer(media_dir).render(
            cards=cards,
            selected_attempts=selected,
            audio_path=audio_path,
            audio_duration=audio_duration,
            prompt=json.dumps({"title": plan.title, "goal": plan.goal_category}, ensure_ascii=True),
        )

        hashtags = _normalize_hashtags(plan.hashtags, self.business.default_hashtags)
        post = GeneratedPost(
            theme=plan.theme,
            hook=plan.title,
            body=_post_body(plan),
            hashtags=hashtags,
            link=self.business.website,
            media=final_media,
        )

        result = LongFormVideoResult(
            post=post,
            plan=plan,
            audio_path=audio_path,
            transcript=transcript,
            cards=cards,
            attempts=clip_attempts,
            selected_attempts=selected,
            final_media=final_media,
            manifest_path=work_dir / "manifest.json",
        )
        _write_manifest(result)
        return result

    def _plan_video(self, source_post: GeneratedPost, *, manual: LongFormManualBrief) -> LongFormPlan:
        target = max(60, min(120, int(self.config.target_seconds or 90)))
        word_target = max(120, min(260, int(target * 2.1)))
        manual_block = ""
        if manual.has_any:
            manual_block = (
                "\nMANUAL OVERRIDES FROM OPERATOR:\n"
                f"- Topic: {manual.topic or '(auto)'}\n"
                f"- Title: {manual.title or '(auto)'}\n"
                f"- Hook: {manual.hook or '(auto)'}\n"
                f"- Payoff: {manual.payoff or '(auto)'}\n"
                "Use these fields exactly when they are supplied, while still grounding claims in context.\n"
            )
        prompt = f"""
Create a narration-led 16:9 long-form social video plan for Hygaar.

BUSINESS:
- Name: {self.business.name}
- Sector: {self.business.sector or '(unspecified)'}
- Product/service: {self.business.product_info or '(unspecified)'}
- Website: {self.business.website or '(none)'}
- Brand voice: {self.business.brand_voice}

SOURCE POST:
- Theme: {source_post.theme}
- Hook/title seed: {source_post.hook}
- Body: {source_post.body}
- Image prompt/context: {source_post.image_prompt or '(none)'}

STRATEGY CONTEXT:
{self.strategy_text[:6000] or '(no strategy docs loaded)'}
{manual_block}

The video must clearly achieve exactly one primary goal from this list:
1. {LONGFORM_GOALS[0]}
2. {LONGFORM_GOALS[1]}
3. {LONGFORM_GOALS[2]}
4. {LONGFORM_GOALS[3]}

Requirements:
- Target duration: about {target} seconds.
- Narration script should be about {word_target} words, clean for ElevenLabs TTS.
- Do not invent product claims. Use docs/context only.
- Focus on offerings, moat, why Hygaar beats an in-house build, or a real feature.
- Make the title direct and useful; score title_alignment_score 1-10 against the selected goal.
- If the title score is under 7, provide a stronger fallback_title.
- Create 4-6 visual_beats. Each beat should be a concrete scene for silent Seedance video.
- No visible captions, no on-screen text, no fake dashboards, no fake logos, no watermark.
- Output ONLY valid JSON.

Return JSON exactly like:
{{
  "theme": "...",
  "title": "...",
  "fallback_title": "...",
  "title_alignment_score": 8,
  "goal_category": "one of the four goals above",
  "hook": "opening narration idea",
  "payoff": "closing payoff / CTA idea",
  "script": "full narration script",
  "linkedin_caption": "short LinkedIn caption to accompany the video",
  "youtube_description": "YouTube description",
  "hashtags": ["#Hygaar", "#AIProductPhotography"],
  "visual_beats": [
    {{"beat": "what this card should show", "avoid": "risks to avoid"}}
  ]
}}
"""
        system = (
            "You are a senior B2B video strategist for Hygaar. "
            "You make narration-led product education videos grounded in supplied context. "
            "Return only JSON."
        )
        try:
            data = self.llm.generate_json(system, prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Long-form planning failed; using fallback plan (%s).", exc)
            data = _fallback_plan_data(source_post, manual, word_target=word_target)

        if manual.title:
            data["title"] = manual.title.strip()
        if manual.hook:
            data["hook"] = manual.hook.strip()
        if manual.payoff:
            data["payoff"] = manual.payoff.strip()
        if manual.topic:
            data["theme"] = manual.topic.strip()
        return _plan_from_data(data, source_post)

    def _build_cards(
        self,
        plan: LongFormPlan,
        transcript: list[TranscriptSegment],
        *,
        duration: float,
    ) -> list[VisualCard]:
        card_count = _card_count(duration, self.config.card_seconds)
        beats = plan.visual_beats or []
        cards: list[VisualCard] = []
        for idx in range(card_count):
            start = duration * idx / card_count
            end = duration * (idx + 1) / card_count
            card_text = _text_for_range(transcript, start=start, end=end)
            if not card_text:
                card_text = _script_slice(plan.script, index=idx, total=card_count)
            beat_data = beats[idx] if idx < len(beats) and isinstance(beats[idx], dict) else {}
            beat = str(beat_data.get("beat") or beat_data.get("visual") or card_text[:140]).strip()
            avoid = str(beat_data.get("avoid") or "").strip()
            prompt = _card_prompt(
                plan=plan,
                card_index=idx + 1,
                card_count=card_count,
                transcript=card_text,
                beat=beat,
                avoid=avoid,
                duration=end - start,
            )
            cards.append(
                VisualCard(
                    index=idx + 1,
                    start=start,
                    end=end,
                    transcript=card_text,
                    beat=beat,
                    prompt=prompt,
                )
            )
        return cards

    def _generate_cards(
        self,
        cards: list[VisualCard],
        *,
        media_dir: Path,
    ) -> tuple[list[ClipAttempt], list[ClipAttempt]]:
        if not self.config.seedance_api_key:
            raise ValueError("Seedance API key is required for long-form video clips.")
        client = SeedanceClient(
            self.config.seedance_api_key,
            base_url=self.config.seedance_base_url,
            model_key=self.config.seedance_model,
            fallback_model_key=self.config.seedance_fallback_model,
        )
        analyzer = GeminiClipQualityAnalyzer(
            api_key=self.config.gemini_api_key,
            model=self.config.qc_model,
            enabled=self.config.qc_enabled,
        )

        attempts: list[ClipAttempt] = []
        selected: list[ClipAttempt] = []
        for card in cards:
            prompt = card.prompt
            card_attempts: list[ClipAttempt] = []
            for attempt_index in range(self.config.max_card_retries + 1):
                try:
                    media = client.generate_video(
                        prompt,
                        media_dir,
                        ratio="16:9",
                        target_duration=max(4, int(math.ceil(card.duration))),
                        clip_count=1,
                        clip_duration=max(4, int(math.ceil(card.duration))),
                        generate_audio=False,
                        watermark=self.config.seedance_watermark,
                    )
                    quality = analyzer.analyze_clip(
                        Path(media.local_path),
                        original_prompt=prompt,
                        card=card,
                        out_dir=media_dir / "qc" / f"card_{card.index}_attempt_{attempt_index}",
                    )
                    attempt = ClipAttempt(
                        card_index=card.index,
                        attempt_index=attempt_index,
                        prompt=prompt,
                        media=media,
                        quality=quality,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Long-form card %s attempt %s failed: %s",
                        card.index,
                        attempt_index,
                        exc,
                    )
                    attempt = ClipAttempt(
                        card_index=card.index,
                        attempt_index=attempt_index,
                        prompt=prompt,
                        media=None,
                        quality=ClipQualityReport(
                            success=False,
                            recommended_retry=True,
                            error=str(exc),
                            overall_quality_score=0,
                            hallucination_percentage=100,
                        ),
                        error=str(exc),
                    )
                attempts.append(attempt)
                card_attempts.append(attempt)

                if attempt.usable and not attempt.quality.needs_retry():
                    break
                if attempt_index < self.config.max_card_retries:
                    prompt = _retry_prompt(card.prompt, attempt.quality, retry_index=attempt_index + 1)

            usable = [item for item in card_attempts if item.usable]
            if not usable:
                raise RuntimeError(f"No usable Seedance clip generated for card {card.index}.")
            selected.append(min(usable, key=lambda item: item.quality.rank_tuple()))
        return attempts, selected


class GeminiClipQualityAnalyzer:
    def __init__(
        self,
        *,
        api_key: Optional[str],
        model: str = "gemini-2.5-flash",
        enabled: bool = True,
    ):
        self.api_key = api_key
        self.model = model or "gemini-2.5-flash"
        self.enabled = enabled

    def analyze_clip(
        self,
        video_path: Path,
        *,
        original_prompt: str,
        card: VisualCard,
        out_dir: Path,
    ) -> ClipQualityReport:
        if not self.enabled:
            return ClipQualityReport(success=True)
        if not self.api_key:
            return ClipQualityReport(
                success=False,
                error="GEMINI_API_KEY is missing; QC skipped.",
                raw_response={"qc_skipped": "missing_gemini_api_key"},
            )
        try:
            frames = _extract_frames(video_path, out_dir=out_dir)
            if not frames:
                return ClipQualityReport(
                    success=False,
                    error="No frames extracted for QC; using clip without retry.",
                )
            from google import genai

            client = genai.Client(api_key=self.api_key)
            prompt = _qc_prompt(original_prompt=original_prompt, card=card)
            parts = [types.Part(text=prompt)]
            for frame_path in frames:
                parts.append(
                    types.Part(
                        inline_data=types.Blob(
                            data=frame_path.read_bytes(),
                            mime_type=mimetypes.guess_type(str(frame_path))[0] or "image/jpeg",
                        )
                    )
                )
            response = client.models.generate_content(
                model=self.model,
                contents=types.Content(role="user", parts=parts),
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    candidate_count=1,
                    max_output_tokens=4096,
                    response_mime_type="application/json",
                ),
            )
            data = _json_from_text(response.text or "")
            return _quality_from_data(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemini long-form clip QC failed: %s", exc)
            return ClipQualityReport(
                success=False,
                error=str(exc),
                raw_response={"qc_error": str(exc)},
            )


class LongFormRenderer:
    def __init__(self, out_dir: Path):
        self.out_dir = Path(out_dir)

    def render(
        self,
        *,
        cards: list[VisualCard],
        selected_attempts: list[ClipAttempt],
        audio_path: Path,
        audio_duration: float,
        prompt: str,
    ) -> GeneratedMedia:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required for long-form video rendering.")
        normalized_dir = self.out_dir / "render_segments"
        normalized_dir.mkdir(parents=True, exist_ok=True)
        normalized: list[Path] = []
        by_card = {attempt.card_index: attempt for attempt in selected_attempts}
        for card in cards:
            attempt = by_card.get(card.index)
            if not attempt or not attempt.media:
                raise RuntimeError(f"Missing selected clip for card {card.index}.")
            out_path = normalized_dir / f"segment_{card.index:02d}.mp4"
            _normalize_clip(
                Path(attempt.media.local_path),
                out_path,
                duration=card.duration,
            )
            normalized.append(out_path)

        joined_path = self.out_dir / f"longform_silent_{int(time.time())}_{uuid.uuid4().hex[:8]}.mp4"
        _concat_normalized_clips(normalized, joined_path)
        final_path = self.out_dir / f"longform_final_{int(time.time())}_{uuid.uuid4().hex[:8]}.mp4"
        return mux_narration_video(
            joined_path,
            audio_path,
            final_path,
            duration=audio_duration,
            prompt=prompt,
        )


def transcribe_audio_openai(
    audio_path: Path,
    *,
    api_key: Optional[str],
    primary_model: str = "gpt-4o-transcribe",
    fallback_model: str = "whisper-1",
) -> list[TranscriptSegment]:
    if not api_key:
        logger.warning("OPENAI_API_KEY missing; using estimated transcript timing.")
        return []
    try:
        from openai import OpenAI
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenAI SDK unavailable for transcription: %s", exc)
        return []

    client = OpenAI(api_key=api_key)
    for model in [primary_model, fallback_model]:
        if not model:
            continue
        try:
            with open(audio_path, "rb") as audio_file:
                kwargs = {
                    "model": model,
                    "file": audio_file,
                    "response_format": "verbose_json",
                }
                if model != "whisper-1":
                    kwargs["timestamp_granularities"] = ["segment"]
                response = client.audio.transcriptions.create(**kwargs)
            segments = _segments_from_transcription_response(response)
            if segments:
                return segments
        except TypeError:
            try:
                with open(audio_path, "rb") as audio_file:
                    response = client.audio.transcriptions.create(
                        model=model,
                        file=audio_file,
                        response_format="verbose_json",
                    )
                segments = _segments_from_transcription_response(response)
                if segments:
                    return segments
            except Exception as exc:  # noqa: BLE001
                logger.warning("OpenAI transcription with %s failed: %s", model, exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI transcription with %s failed: %s", model, exc)
    return []


def _segments_from_transcription_response(response) -> list[TranscriptSegment]:
    raw_segments = None
    if isinstance(response, dict):
        raw_segments = response.get("segments")
    else:
        raw_segments = getattr(response, "segments", None)
        if raw_segments is None and hasattr(response, "model_dump"):
            raw_segments = response.model_dump().get("segments")
    out: list[TranscriptSegment] = []
    for segment in raw_segments or []:
        if isinstance(segment, dict):
            start = segment.get("start", 0)
            end = segment.get("end", start)
            text = segment.get("text", "")
        else:
            start = getattr(segment, "start", 0)
            end = getattr(segment, "end", start)
            text = getattr(segment, "text", "")
        try:
            out.append(
                TranscriptSegment(
                    start=float(start),
                    end=float(end),
                    text=str(text).strip(),
                )
            )
        except (TypeError, ValueError):
            continue
    return [segment for segment in out if segment.text]


def _estimate_transcript(script: str, *, duration: float) -> list[TranscriptSegment]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
    if not sentences:
        sentences = [script.strip()]
    total_words = sum(max(1, len(sentence.split())) for sentence in sentences)
    current = 0.0
    segments = []
    for sentence in sentences:
        word_share = max(1, len(sentence.split())) / max(1, total_words)
        seg_duration = duration * word_share
        end = min(duration, current + seg_duration)
        segments.append(TranscriptSegment(start=current, end=end, text=sentence))
        current = end
    if segments:
        segments[-1].end = duration
    return segments


def _probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required for long-form video timing.")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe duration failed: {result.stderr[-300:]}")
    try:
        return max(1.0, float(result.stdout.strip()))
    except ValueError as exc:
        raise RuntimeError(f"Could not parse duration for {path}: {result.stdout!r}") from exc


def _card_count(duration: float, card_seconds: int) -> int:
    desired = int(round(duration / max(12, card_seconds or 18)))
    return max(4, min(6, desired))


def _text_for_range(transcript: list[TranscriptSegment], *, start: float, end: float) -> str:
    parts = []
    for segment in transcript:
        overlaps = segment.end > start and segment.start < end
        if overlaps and segment.text:
            parts.append(segment.text)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _script_slice(script: str, *, index: int, total: int) -> str:
    words = script.split()
    if not words:
        return ""
    start = int(len(words) * index / total)
    end = int(len(words) * (index + 1) / total)
    return " ".join(words[start:end]).strip()


def _card_prompt(
    *,
    plan: LongFormPlan,
    card_index: int,
    card_count: int,
    transcript: str,
    beat: str,
    avoid: str,
    duration: float,
) -> str:
    avoid_clause = f"Specific risks to avoid: {avoid}." if avoid else ""
    return (
        f"Create a silent {int(math.ceil(duration))}-second 16:9 cinematic B2B product video clip "
        f"for Hygaar. This is card {card_index} of {card_count} in a narration-led video.\n"
        f"Video title: {plan.title}\n"
        f"Primary goal: {plan.goal_category}\n"
        f"Narration covered in this card: {transcript[:900]}\n"
        f"Visual beat: {beat}\n"
        f"{avoid_clause}\n"
        "Visual requirements: premium ecommerce/product-media operations, realistic fashion/beauty/home "
        "catalogue assets, product references becoming production-ready images and videos, controlled "
        "lighting, coherent camera motion, accurate human anatomy if people appear, stable objects and "
        "realistic physics. No readable text, no captions, no fake dashboard UI, no fake logos, no "
        "watermark, no distorted products, no extra limbs, no warped hands, no impossible motion. "
        "Make it cut cleanly with adjacent clips."
    )


def _qc_prompt(*, original_prompt: str, card: VisualCard) -> str:
    return f"""
Analyze these sampled frames from one AI-generated video clip.

Original Seedance prompt:
{original_prompt[:2500]}

Narration segment:
{card.transcript[:1200]}

Detect visual hallucinations or severe quality problems:
- anatomical errors, extra/missing limbs, warped hands or faces
- product distortion, object clipping, floating objects
- impossible physics or temporal inconsistency
- unstable backgrounds, obvious artifacts, malformed UI/logos/text

Be strict about hallucinations, but do not fail a clip only because it is stylistically simple.

Return ONLY valid JSON:
{{
  "overall_quality_score": 1,
  "has_hallucinations": false,
  "hallucination_severity": "none|minor|moderate|severe",
  "hallucination_percentage": 0,
  "recommended_retry": false,
  "issues_detected": [
    {{
      "type": "anatomical|object|temporal|background|text|other",
      "description": "...",
      "severity": "minor|moderate|severe",
      "frame_index": 0,
      "confidence": 0.0
    }}
  ],
  "improvement_suggestions": {{
    "prompt_modifications": "...",
    "technical_improvements": "...",
    "focus_areas": ["..."],
    "new_full_prompt": "complete safer replacement prompt"
  }},
  "confidence_score": 0.0
}}
"""


def _quality_from_data(data: dict) -> ClipQualityReport:
    suggestions = data.get("improvement_suggestions") or {}
    if not isinstance(suggestions, dict):
        suggestions = {}
    new_prompt = suggestions.get("new_full_prompt") or data.get("new_prompt")
    issues = data.get("issues_detected") or []
    if not isinstance(issues, list):
        issues = []
    return ClipQualityReport(
        success=True,
        has_hallucinations=bool(data.get("has_hallucinations", False)),
        hallucination_severity=str(data.get("hallucination_severity", "none")).lower(),
        hallucination_percentage=_as_int(data.get("hallucination_percentage"), 0, 100),
        overall_quality_score=_as_int(data.get("overall_quality_score"), 1, 10, default=8),
        recommended_retry=bool(data.get("recommended_retry", False)),
        issues_detected=issues,
        improvement_suggestions=suggestions,
        new_prompt=str(new_prompt).strip() if new_prompt else None,
        raw_response=data,
    )


def _retry_prompt(original_prompt: str, quality: ClipQualityReport, *, retry_index: int) -> str:
    if quality.new_prompt and len(quality.new_prompt.strip()) > 80:
        return quality.new_prompt.strip()
    issues = []
    for issue in quality.issues_detected[:6]:
        desc = issue.get("description") if isinstance(issue, dict) else str(issue)
        if desc:
            issues.append(str(desc))
    issue_text = "; ".join(issues) or quality.error or "visual instability"
    return (
        f"{original_prompt}\n\n"
        f"Correction pass {retry_index}: the previous clip had these issues: {issue_text}. "
        "Regenerate with simpler camera motion, more stable composition, realistic anatomy and "
        "physics, no object distortion, no readable text, no fake UI, no warped hands or faces. "
        "Keep the same scene intent but prioritize clean, believable visuals."
    )


def _extract_frames(video_path: Path, *, out_dir: Path, frame_count: int = 6) -> list[Path]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for clip QC frame extraction.")
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = _probe_duration(video_path)
    fps = max(0.1, min(1.0, frame_count / max(1.0, duration)))
    pattern = out_dir / "frame_%02d.jpg"
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"fps={fps:.4f},scale=960:-2",
            "-frames:v",
            str(frame_count),
            "-q:v",
            "3",
            str(pattern),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed: {result.stderr[-500:]}")
    return sorted(out_dir.glob("frame_*.jpg"))[:frame_count]


def _normalize_clip(source: Path, out_path: Path, *, duration: float) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for long-form video rendering.")
    vf = (
        "scale=1920:1080:force_original_aspect_ratio=increase,"
        "crop=1920:1080,fps=30,setsar=1,format=yuv420p"
    )
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(source),
            "-t",
            f"{max(4.0, duration):.3f}",
            "-vf",
            vf,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg segment normalize failed: {result.stderr[-500:]}")


def _concat_normalized_clips(clips: list[Path], out_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for long-form video rendering.")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as manifest:
        manifest_path = Path(manifest.name)
        for clip in clips:
            escaped = str(clip.resolve()).replace("'", "'\\''")
            manifest.write(f"file '{escaped}'\n")
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(manifest_path),
                "-c",
                "copy",
                str(out_path),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg long-form concat failed: {result.stderr[-500:]}")
    finally:
        manifest_path.unlink(missing_ok=True)


def _json_from_text(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw[:-3]
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            return json.loads(raw[start : end + 1])
        raise


def _plan_from_data(data: dict, source_post: GeneratedPost) -> LongFormPlan:
    visual_beats = data.get("visual_beats") or []
    if not isinstance(visual_beats, list):
        visual_beats = []
    script = str(data.get("script") or "").strip()
    if not script:
        script = _fallback_script(source_post)
    return LongFormPlan(
        theme=str(data.get("theme") or source_post.theme).strip(),
        title=str(data.get("title") or source_post.hook or source_post.theme).strip(),
        fallback_title=str(data.get("fallback_title") or source_post.hook or source_post.theme).strip(),
        title_alignment_score=_as_int(data.get("title_alignment_score"), 1, 10, default=7),
        goal_category=_valid_goal(data.get("goal_category")),
        hook=str(data.get("hook") or source_post.hook).strip(),
        payoff=str(data.get("payoff") or "See what Hygaar can automate for your catalogue workflow.").strip(),
        script=script,
        linkedin_caption=str(data.get("linkedin_caption") or source_post.body).strip(),
        youtube_description=str(data.get("youtube_description") or source_post.body).strip(),
        hashtags=[str(tag).strip() for tag in data.get("hashtags") or [] if str(tag).strip()],
        visual_beats=visual_beats,
    )


def _fallback_plan_data(
    source_post: GeneratedPost,
    manual: LongFormManualBrief,
    *,
    word_target: int,
) -> dict:
    title = manual.title or source_post.hook or "Why Hygaar beats an in-house content pipeline"
    hook = manual.hook or source_post.hook or "Most ecommerce teams do not need more tools."
    payoff = manual.payoff or "Hygaar gives teams the production layer without hiring the whole stack."
    script = _fallback_script(source_post, hook=hook, payoff=payoff, word_target=word_target)
    return {
        "theme": manual.topic or source_post.theme,
        "title": title,
        "fallback_title": "Why Hygaar beats an in-house AI media team",
        "title_alignment_score": 7,
        "goal_category": LONGFORM_GOALS[2],
        "hook": hook,
        "payoff": payoff,
        "script": script,
        "linkedin_caption": source_post.body,
        "youtube_description": source_post.body,
        "hashtags": ["#Hygaar", "#AIProductPhotography", "#EcommerceAI"],
        "visual_beats": [
            {"beat": "Ecommerce catalogue team facing many SKU image requests"},
            {"beat": "AI production workflow turning references into consistent product media"},
            {"beat": "Quality review and variant consistency at scale"},
            {"beat": "Final marketplace, PDP, social and ad assets ready for launch"},
        ],
    }


def _fallback_script(
    source_post: GeneratedPost,
    *,
    hook: Optional[str] = None,
    payoff: Optional[str] = None,
    word_target: int = 180,
) -> str:
    start = hook or source_post.hook or "Building an in-house AI media pipeline looks simple from the outside."
    end = payoff or "That is the reason teams use Hygaar: production quality, workflow control, and speed without rebuilding the stack."
    middle = (
        "The hard part is not just generating one attractive image or one short video. "
        "The hard part is keeping every SKU, model, fabric, variant, background, and campaign asset consistent across channels. "
        "You need prompts, model routing, reference handling, quality checks, retries, delivery formats, and a way for operators to trust the result. "
        "Hygaar is built as that production layer for ecommerce teams. It turns product references and catalogue context into ready-to-use product media, "
        "with agentic workflows around generation, review, and delivery. Instead of hiring a full internal research, engineering, creative, and QA stack, "
        "a brand can plug into a system that already understands catalogue media at scale."
    )
    script = f"{start} {middle} {end}"
    words = script.split()
    if len(words) > word_target + 40:
        script = " ".join(words[: word_target + 40]).rstrip(".,;:") + "."
    return script


def _valid_goal(value) -> str:
    text = str(value or "").strip()
    for goal in LONGFORM_GOALS:
        if text.lower() == goal.lower():
            return goal
    lowered = text.lower()
    if "moat" in lowered:
        return LONGFORM_GOALS[1]
    if "house" in lowered or "build" in lowered:
        return LONGFORM_GOALS[2]
    if "feature" in lowered:
        return LONGFORM_GOALS[3]
    return LONGFORM_GOALS[0]


def _as_int(value, low: int, high: int, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _normalize_hashtags(values: list[str], defaults: list[str]) -> list[str]:
    out: list[str] = []
    for raw in [*values, *defaults]:
        tag = str(raw).strip()
        if not tag:
            continue
        tag = tag if tag.startswith("#") else f"#{tag}"
        if tag.lower() not in {item.lower() for item in out}:
            out.append(tag)
        if len(out) >= 8:
            break
    return out or ["#Hygaar", "#EcommerceAI", "#AIProductPhotography"]


def _post_body(plan: LongFormPlan) -> str:
    caption = plan.linkedin_caption.strip() or plan.youtube_description.strip()
    if plan.payoff and plan.payoff not in caption:
        caption = f"{caption}\n\n{plan.payoff}".strip()
    return caption


def _write_manifest(result: LongFormVideoResult) -> None:
    payload = {
        "plan": asdict(result.plan),
        "audio_path": str(result.audio_path),
        "transcript": [asdict(segment) for segment in result.transcript],
        "cards": [asdict(card) for card in result.cards],
        "attempts": [
            {
                "card_index": attempt.card_index,
                "attempt_index": attempt.attempt_index,
                "prompt": attempt.prompt,
                "media": attempt.media.model_dump(mode="json") if attempt.media else None,
                "quality": asdict(attempt.quality),
                "error": attempt.error,
            }
            for attempt in result.attempts
        ],
        "selected_attempts": [
            {
                "card_index": attempt.card_index,
                "attempt_index": attempt.attempt_index,
                "media_local_path": attempt.media.local_path if attempt.media else None,
                "quality": asdict(attempt.quality),
            }
            for attempt in result.selected_attempts
        ],
        "final_media": result.final_media.model_dump(mode="json"),
    }
    result.manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
