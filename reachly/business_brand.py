"""Business-owned image inputs. No environment or default-logo lookup."""
import base64
import hashlib
import io
import re
from pathlib import Path
from PIL import Image


def palette(values):
    if not isinstance(values, list) or len(values) > 6:
        raise ValueError("Provide at most six brand colours")
    if any(not isinstance(v, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", v.strip()) for v in values):
        raise ValueError("Brand colours must be six-digit hex colours")
    return [v.strip().lower() for v in values]


def logo_file(encoded, directory):
    if not encoded:
        return None
    if not isinstance(encoded, str) or len(encoded) > 2_800_000:
        raise ValueError("Logo must be a PNG/JPEG under 2 MB")
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > 2_000_000:
        raise ValueError("Logo exceeds 2 MB")
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in {"PNG", "JPEG"} or max(image.size) > 4096:
            raise ValueError("Invalid logo format or dimensions")
        image.load()
        target = Path(directory) / (hashlib.sha256(raw).hexdigest() + ".png")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        image.convert("RGBA").save(target, format="PNG")
    return str(target)
