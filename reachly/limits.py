"""Shared media limits for generation, handoff and publishing paths."""
from __future__ import annotations

import os


IMAGE_MAX_BYTES = int(os.environ.get("REACHLY_IMAGE_MAX_BYTES", str(15 * 1024 * 1024)))
