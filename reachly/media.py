"""Media generation: images (Gemini "Nano Banana") and optional video/image via
the user's Hygaar account.

Every generator returns a GeneratedMedia with a local file path. Publishing
adapters decide whether they also need a public URL (Instagram API does).
"""
from __future__ import annotations

import logging
import math
import shutil
import subprocess
import time
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import requests

from .models import GeneratedMedia

logger = logging.getLogger("reachly.media")

SEEDANCE_DEFAULT_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"
SEEDANCE_MODELS = {
    "seedance_2_0": "dreamina-seedance-2-0-260128",
    "seedance_2_0_fast": "dreamina-seedance-2-0-fast-260128",
    "seedance_2_5": "dreamina-seedance-2-5-260628",
}
SEEDANCE_MODEL_MAX_SECONDS = {
    "seedance_2_0": 15,
    "seedance_2_0_fast": 15,
    "seedance_2_5": 30,
}
SEEDANCE_MODEL_REFERENCE_IMAGE_LIMITS = {
    "seedance_2_0": 12,
    "seedance_2_0_fast": 12,
    # Seedance 2.5 accepts up to 50 total assets: 30 images, 10 videos, 10 audio.
    "seedance_2_5": 30,
}
SEEDANCE_ALLOWED_RATIOS = {"21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "adaptive"}

_URL_KEYS = (
    "url",
    "image_url",
    "video_url",
    "output_url",
    "generated_image_url",
    "result_url",
    "cdn_url",
    "signed_url",
)


def _first_url(obj) -> Optional[str]:
    """Recursively find the first plausible media URL in a Hygaar response."""
    if isinstance(obj, dict):
        for k in _URL_KEYS:
            v = obj.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
        for v in obj.values():
            found = _first_url(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _first_url(v)
            if found:
                return found
    return None


def _validate_seedance_ratio(ratio: str) -> str:
    if ratio in SEEDANCE_ALLOWED_RATIOS:
        return ratio
    return {
        "portrait": "9:16",
        "landscape": "16:9",
        "square": "1:1",
    }.get((ratio or "").lower(), "9:16")


def _normalize_seedance_status(status: str) -> str:
    mapping = {
        "queued": "processing",
        "running": "processing",
        "processing": "processing",
        "succeeded": "completed",
        "success": "completed",
        "completed": "completed",
        "done": "completed",
        "failed": "failed",
        "error": "failed",
        "expired": "failed",
    }
    return mapping.get((status or "").lower(), status or "unknown")


def resolve_seedance_model(model_key: str | None = None) -> str:
    if model_key in SEEDANCE_MODELS:
        return SEEDANCE_MODELS[model_key]
    if model_key and str(model_key).startswith("dreamina-"):
        return str(model_key)
    return SEEDANCE_MODELS["seedance_2_5"]


def _seedance_model_key(model_key: str | None) -> str:
    if model_key in SEEDANCE_MODELS:
        return str(model_key)
    for key, model_id in SEEDANCE_MODELS.items():
        if model_key == model_id:
            return key
    return "seedance_2_5"


def _seedance_reference_limit(model_key: str) -> int:
    return SEEDANCE_MODEL_REFERENCE_IMAGE_LIMITS.get(_seedance_model_key(model_key), 12)


def _normalize_reference_images(reference_images: Optional[list]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for ref in reference_images or []:
        url = ""
        role = "reference_image"
        if isinstance(ref, str):
            url = ref
        elif isinstance(ref, dict):
            raw_url = ref.get("url") or ref.get("image_url")
            if isinstance(raw_url, dict):
                raw_url = raw_url.get("url")
            url = raw_url or ""
            role = ref.get("role") or role
        if (
            not isinstance(url, str)
            or not url.startswith(("http://", "https://", "data:image/"))
            or url in seen
        ):
            continue
        seen.add(url)
        out.append({"url": url, "role": role})
    return out


def _seedance_content(prompt: str, model_key: str, reference_images: Optional[list]) -> list[dict]:
    content: list[dict] = [{"type": "text", "text": prompt}]
    limit = _seedance_reference_limit(model_key)
    for ref in _normalize_reference_images(reference_images)[:limit]:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": ref["url"]},
                "role": "reference_image",
            }
        )
    return content


def _seedance_audio_policy_error(error: Exception) -> bool:
    text = str(error).lower()
    return "outputaudiosensitivecontentdetected" in text or "output audio" in text


# ----------------------------------------------------------------------
# Gemini image generation (Nano Banana)
# ----------------------------------------------------------------------
def generate_image_gemini(
    prompt: str,
    *,
    api_key: Optional[str],
    model: str = "gemini-2.5-flash-image",
    out_dir: Path,
    logo_path: Optional[str] = None,
    logo_position: str = "bottom-right",
    aspect_ratio: str = "1:1",
) -> GeneratedMedia:
    from google import genai

    client = genai.Client(api_key=api_key)
    full_prompt = (
        f"{prompt}\n\nStyle: clean, professional, social-media ready, "
        f"no text, no watermark, no fake logo. Leave clean corner space for "
        f"the provided brand logo. Aspect ratio roughly {aspect_ratio}."
    )
    resp = client.models.generate_content(model=model, contents=[full_prompt])

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"image_{int(time.time())}_{uuid.uuid4().hex[:8]}.png"

    for part in resp.candidates[0].content.parts:
        inline = getattr(part, "inline_data", None)
        if inline is not None and getattr(inline, "data", None):
            path.write_bytes(inline.data)
            _apply_logo_overlay(path, logo_path=logo_path, position=logo_position)
            return GeneratedMedia(
                kind="image",
                local_path=str(path),
                mime_type=inline.mime_type or "image/png",
                prompt=prompt,
            )
    raise RuntimeError("Gemini returned no image data for the prompt.")


def _apply_logo_overlay(
    image_path: Path,
    *,
    logo_path: Optional[str],
    position: str = "bottom-right",
    max_width_ratio: float = 0.18,
    opacity: float = 0.92,
) -> None:
    if not logo_path:
        return
    logo_file = Path(logo_path).expanduser()
    if not logo_file.is_file():
        logger.warning("Brand logo not found for overlay: %s", logo_file)
        return
    try:
        from PIL import Image

        with Image.open(image_path).convert("RGBA") as base:
            with Image.open(logo_file) as raw_logo:
                logo = _logo_with_transparency(raw_logo)
                max_w = max(48, int(base.width * max_width_ratio))
                scale = min(1.0, max_w / max(1, logo.width))
                size = (max(1, int(logo.width * scale)), max(1, int(logo.height * scale)))
                logo = logo.resize(size, Image.LANCZOS)
                if opacity < 1:
                    alpha = logo.getchannel("A").point(lambda p: int(p * opacity))
                    logo.putalpha(alpha)
                margin = max(24, int(base.width * 0.035))
                x = margin if "left" in position else base.width - logo.width - margin
                y = margin if "top" in position else base.height - logo.height - margin
                base.alpha_composite(logo, (x, y))
                base.convert("RGB").save(image_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("Brand logo overlay failed for %s: %s", image_path, e)


def _logo_with_transparency(image):
    """Convert common white-background logo exports into transparent overlays."""
    from PIL import Image

    logo = image.convert("RGBA")
    if image.mode in ("RGBA", "LA") and logo.getchannel("A").getextrema()[0] < 255:
        return logo

    pixels = logo.load()
    width, height = logo.size
    corners = [
        pixels[0, 0][:3],
        pixels[width - 1, 0][:3],
        pixels[0, height - 1][:3],
        pixels[width - 1, height - 1][:3],
    ]
    if not all(min(corner) >= 235 for corner in corners):
        return logo

    data = []
    for r, g, b, a in logo.getdata():
        whiteness = min(r, g, b)
        if whiteness >= 252:
            data.append((r, g, b, 0))
        elif whiteness >= 235 and max(r, g, b) - min(r, g, b) <= 24:
            alpha = int((252 - whiteness) / 17 * a)
            data.append((r, g, b, max(0, min(a, alpha))))
        else:
            data.append((r, g, b, a))
    logo.putdata(data)
    return logo


# ----------------------------------------------------------------------
# Hygaar provider (uses the user's Hygaar account / API)
# ----------------------------------------------------------------------
class HygaarClient:
    """Client for the Hygaar media pipeline (https://*.hygaar.com).

    Auth is via the ``X-API-Key`` header (keys look like ``hygaar_...``). The
    flow is: POST a generation request -> receive a ``batch_id`` ->
    poll ``/api/batch/generation-status/`` until URLs appear.

    Endpoint paths + the request payload are configurable because Hygaar exposes
    several generators (campaign, images, video pipeline). Defaults target the
    documented image/video endpoints; pass ``image_endpoint`` / ``video_endpoint``
    / ``payload_extra`` to adapt to your Hygaar account's generator.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: int = 30,
        image_endpoint: str = "/api/batch/generate-images/",
        video_endpoint: str = "/api/video-pipeline/generate/",
        status_endpoint: str = "/api/batch/generation-status/",
        video_status_endpoint: str = "/api/video-pipeline/generation-status/",
        payload_extra: Optional[dict] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.image_endpoint = image_endpoint
        self.video_endpoint = video_endpoint
        self.status_endpoint = status_endpoint
        self.video_status_endpoint = video_status_endpoint
        self.payload_extra = payload_extra or {}

    def _headers(self) -> dict:
        return {"X-API-Key": self.api_key, "Content-Type": "application/json"}

    def generate_image(
        self,
        prompt: str,
        out_dir: Path,
        *,
        logo_path: Optional[str] = None,
        logo_position: str = "bottom-right",
    ) -> GeneratedMedia:
        payload = {"prompt": prompt, "count": 1, **self.payload_extra}
        resp = requests.post(
            f"{self.base_url}{self.image_endpoint}",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        image_url = self._await_asset(resp.json(), kind="image")
        media = self._download(image_url, out_dir, kind="image")
        _apply_logo_overlay(
            Path(media.local_path),
            logo_path=logo_path,
            position=logo_position,
        )
        return media

    def generate_video(self, prompt: str, out_dir: Path) -> GeneratedMedia:
        payload = {"prompt": prompt, **self.payload_extra}
        resp = requests.post(
            f"{self.base_url}{self.video_endpoint}",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        video_url = self._await_asset(resp.json(), kind="video")
        return self._download(video_url, out_dir, kind="video")

    def _await_asset(self, job: dict, *, kind: str, max_wait: int = 600) -> str:
        # If the API returned a direct url, use it.
        url = _first_url(job)
        if url:
            return url
        batch_id = job.get("batch_id") or job.get("job_id") or job.get("id")
        if not batch_id:
            raise RuntimeError(f"Hygaar response had no asset url or batch id: {job}")

        status_path = self.video_status_endpoint if kind == "video" else self.status_endpoint
        deadline = time.time() + max_wait
        while time.time() < deadline:
            r = requests.get(
                f"{self.base_url}{status_path}",
                params={"batch_id": batch_id},
                headers=self._headers(),
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
            state = str(data.get("status", "")).lower()
            url = _first_url(data)
            if url and state in ("", "done", "completed", "succeeded", "success", "ready"):
                return url
            if state in ("failed", "error"):
                raise RuntimeError(f"Hygaar generation failed: {data}")
            time.sleep(5)
        raise TimeoutError("Hygaar generation timed out.")

    def _download(self, url: str, out_dir: Path, *, kind: str) -> GeneratedMedia:
        out_dir.mkdir(parents=True, exist_ok=True)
        ext = "mp4" if kind == "video" else "png"
        path = out_dir / f"{kind}_{int(time.time())}.{ext}"
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
        mime = "video/mp4" if kind == "video" else "image/png"
        return GeneratedMedia(kind=kind, local_path=str(path), mime_type=mime, public_url=url)


# ----------------------------------------------------------------------
# Seedance provider (BytePlus ModelArk)
# ----------------------------------------------------------------------
class SeedanceClient:
    """Direct Seedance video generation via BytePlus ModelArk.

    Reachly mirrors the payload shape already used by Hygaar Agent 8:
    POST /contents/generations/tasks, then poll the task until content.video_url
    is available. For multi-scene social videos, multiple 15s clips can be
    generated and concatenated locally with ffmpeg.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = SEEDANCE_DEFAULT_BASE_URL,
        model_key: str = "seedance_2_5",
        fallback_model_key: str = "seedance_2_0",
        timeout: int = 60,
        poll_interval: int = 15,
        max_poll_attempts: int = 120,
    ):
        if not api_key:
            raise ValueError("Seedance API key is required.")
        self.api_key = api_key
        self.base_url = (base_url or SEEDANCE_DEFAULT_BASE_URL).rstrip("/")
        self.model_key = _seedance_model_key(model_key)
        self.fallback_model_key = _seedance_model_key(fallback_model_key)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_poll_attempts = max_poll_attempts

    def generate_video(
        self,
        prompt: str,
        out_dir: Path,
        *,
        ratio: str = "9:16",
        target_duration: int = 30,
        clip_count: int = 0,
        clip_duration: int = 15,
        generate_audio: bool = True,
        watermark: bool = False,
        reference_images: Optional[list] = None,
    ) -> GeneratedMedia:
        try:
            return self._generate_video_with_fallback(
                prompt,
                out_dir,
                ratio=ratio,
                target_duration=target_duration,
                clip_count=clip_count,
                clip_duration=clip_duration,
                generate_audio=generate_audio,
                watermark=watermark,
                reference_images=reference_images,
            )
        except Exception as error:
            if generate_audio and _seedance_audio_policy_error(error):
                logger.warning(
                    "Seedance audio generation was rejected by policy; retrying video without audio."
                )
                return self._generate_video_with_fallback(
                    prompt,
                    out_dir,
                    ratio=ratio,
                    target_duration=target_duration,
                    clip_count=clip_count,
                    clip_duration=clip_duration,
                    generate_audio=False,
                    watermark=watermark,
                    reference_images=reference_images,
                )
            raise

    def _generate_video_with_fallback(
        self,
        prompt: str,
        out_dir: Path,
        *,
        ratio: str,
        target_duration: int,
        clip_count: int,
        clip_duration: int,
        generate_audio: bool,
        watermark: bool,
        reference_images: Optional[list],
    ) -> GeneratedMedia:
        try:
            return self._generate_video_for_model(
                self.model_key,
                prompt,
                out_dir,
                ratio=ratio,
                target_duration=target_duration,
                clip_count=clip_count,
                clip_duration=clip_duration,
                generate_audio=generate_audio,
                watermark=watermark,
                reference_images=reference_images,
            )
        except Exception as primary_error:
            if self.model_key == self.fallback_model_key or not self.fallback_model_key:
                raise
            logger.warning(
                "Seedance %s generation failed (%s); retrying with %s.",
                self.model_key,
                primary_error,
                self.fallback_model_key,
            )
            return self._generate_video_for_model(
                self.fallback_model_key,
                prompt,
                out_dir,
                ratio=ratio,
                target_duration=target_duration,
                clip_count=clip_count,
                clip_duration=clip_duration,
                generate_audio=generate_audio,
                watermark=watermark,
                reference_images=reference_images,
            )

    def _generate_video_for_model(
        self,
        model_key: str,
        prompt: str,
        out_dir: Path,
        *,
        ratio: str,
        target_duration: int,
        clip_count: int,
        clip_duration: int,
        generate_audio: bool,
        watermark: bool,
        reference_images: Optional[list],
    ) -> GeneratedMedia:
        durations = self._clip_durations(
            model_key=model_key,
            target_duration=target_duration,
            clip_count=clip_count,
            clip_duration=clip_duration,
        )
        clips: list[GeneratedMedia] = []
        for index, duration in enumerate(durations, start=1):
            segment_prompt = self._segment_prompt(prompt, index=index, total=len(durations))
            task_id = self._create_task(
                model_key,
                segment_prompt,
                ratio=ratio,
                duration=duration,
                generate_audio=generate_audio,
                watermark=watermark,
                reference_images=reference_images,
            )
            video_url = self._await_video_url(task_id)
            clips.append(self._download(video_url, out_dir, kind="video", suffix=f"clip{index}"))

        if len(clips) == 1:
            media = clips[0]
            media.prompt = prompt
            return media
        return self._concat_videos(clips, out_dir, prompt=prompt)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _clip_durations(
        self,
        *,
        model_key: str,
        target_duration: int,
        clip_count: int,
        clip_duration: int,
    ) -> list[int]:
        max_single = SEEDANCE_MODEL_MAX_SECONDS.get(model_key, 30)
        target = max(4, min(45, int(target_duration or 30)))
        preferred = max(4, min(max_single, int(clip_duration or 15)))
        if clip_count and int(clip_count) > 0:
            count = max(1, min(3, int(clip_count)))
        else:
            if target <= max_single:
                return [target]
            count = max(1, min(3, math.ceil(target / preferred)))
        if count == 1:
            return [max(4, min(max_single, target))]

        remaining = target
        durations: list[int] = []
        for idx in range(count):
            remaining_clips = count - idx
            duration = min(max_single, max(4, round(remaining / remaining_clips)))
            durations.append(duration)
            remaining -= duration
        return durations

    def _segment_prompt(self, prompt: str, *, index: int, total: int) -> str:
        if total <= 1:
            return prompt
        return (
            f"{prompt}\n\n"
            f"Segment {index} of {total}: create a distinct camera angle and scene beat "
            "that can cut cleanly with the other segments. Keep subject and brand "
            "continuity, avoid on-screen text, and end on a clean transition frame."
        )

    def _create_task(
        self,
        model_key: str,
        prompt: str,
        *,
        ratio: str,
        duration: int,
        generate_audio: bool,
        watermark: bool,
        reference_images: Optional[list] = None,
    ) -> str:
        payload = {
            "model": resolve_seedance_model(model_key),
            "content": _seedance_content(prompt, model_key, reference_images),
            "ratio": _validate_seedance_ratio(ratio),
            "duration": duration,
            "generate_audio": generate_audio,
            "watermark": watermark,
        }
        resp = requests.post(
            f"{self.base_url}/contents/generations/tasks",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        data = self._json_or_error(resp)
        if resp.status_code not in (200, 201) or not data.get("id"):
            code = data.get("code")
            message = data.get("message") or data.get("error") or resp.text[:300]
            if code:
                message = f"{code}: {message}"
            raise RuntimeError(f"Seedance task creation failed ({resp.status_code}): {message}")
        return data["id"]

    def _await_video_url(self, task_id: str) -> str:
        for attempt in range(self.max_poll_attempts):
            resp = requests.get(
                f"{self.base_url}/contents/generations/tasks/{task_id}",
                headers=self._headers(),
                timeout=min(30, self.timeout),
            )
            data = self._json_or_error(resp)
            if resp.status_code >= 300:
                if attempt < 3:
                    time.sleep(self.poll_interval)
                    continue
                raise RuntimeError(
                    f"Seedance status check failed ({resp.status_code}): {resp.text[:300]}"
                )
            status = _normalize_seedance_status(data.get("status", "processing"))
            if status == "completed":
                content = data.get("content") or {}
                video_url = content.get("video_url") or _first_url(content) or _first_url(data)
                if not video_url:
                    raise RuntimeError(f"Seedance task completed without video_url: {data}")
                return video_url
            if status == "failed":
                raise RuntimeError(data.get("error") or data.get("message") or "Seedance task failed.")
            time.sleep(self.poll_interval)
        raise TimeoutError(f"Seedance task timed out: {task_id}")

    def _json_or_error(self, resp) -> dict:
        try:
            return resp.json()
        except ValueError as exc:
            raise RuntimeError(f"Seedance returned non-JSON response: {resp.text[:300]}") from exc

    def _download(self, url: str, out_dir: Path, *, kind: str, suffix: str = "") -> GeneratedMedia:
        out_dir.mkdir(parents=True, exist_ok=True)
        ext = "mp4" if kind == "video" else "png"
        token = f"_{suffix}" if suffix else ""
        path = out_dir / f"{kind}_{int(time.time())}_{uuid.uuid4().hex[:8]}{token}.{ext}"
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
        mime = "video/mp4" if kind == "video" else "image/png"
        return GeneratedMedia(kind=kind, local_path=str(path), mime_type=mime, public_url=url)

    def _concat_videos(
        self,
        clips: list[GeneratedMedia],
        out_dir: Path,
        *,
        prompt: str,
    ) -> GeneratedMedia:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required to concatenate Seedance video clips.")
        out_dir.mkdir(parents=True, exist_ok=True)
        final_path = out_dir / f"video_{int(time.time())}_{uuid.uuid4().hex[:8]}.mp4"
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as manifest:
            manifest_path = Path(manifest.name)
            for clip in clips:
                clip_path = Path(clip.local_path).resolve()
                escaped_path = str(clip_path).replace("'", "'\\''")
                manifest.write(f"file '{escaped_path}'\n")
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
                    str(final_path),
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg concat failed: {result.stderr[-500:]}")
        finally:
            manifest_path.unlink(missing_ok=True)
        return GeneratedMedia(
            kind="video",
            local_path=str(final_path),
            mime_type="video/mp4",
            public_url=None,
            prompt=prompt,
        )
