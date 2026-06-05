"""Media generation: images (Gemini "Nano Banana") and optional video/image via
the user's Hygaar account.

Every generator returns a GeneratedMedia with a local file path. Publishing
adapters decide whether they also need a public URL (Instagram API does).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import requests

from .models import GeneratedMedia

logger = logging.getLogger("reachly.media")

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
) -> GeneratedMedia:
    from google import genai

    client = genai.Client(api_key=api_key)
    full_prompt = (
        f"{prompt}\n\nStyle: clean, professional, social-media ready, "
        f"no text, no watermark, no fake logo. Leave clean corner space for "
        f"the provided brand logo. Aspect ratio roughly 1:1."
    )
    resp = client.models.generate_content(model=model, contents=[full_prompt])

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"image_{int(time.time())}.png"

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
    max_width_ratio: float = 0.14,
    opacity: float = 0.86,
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
            with Image.open(logo_file).convert("RGBA") as logo:
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
