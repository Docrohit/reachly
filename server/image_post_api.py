"""Personal, workspace-scoped image-post API. Generation never publishes."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import uuid
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlmodel import SQLModel, Field as DBField, select
from reachly import generation_store as store
from reachly.generation_worker import process
from reachly.generation_contract import Brand, CreativeBrief, GenerationRequest
from reachly.models import BusinessProfile
from reachly.visual import ReferenceImage, VisualOptions, validate_options
from .crypto import decrypt_dict
from .db import User, get_session
from .studio import _key, _profile

logger = logging.getLogger(__name__)
router = APIRouter()
_tasks = set()


class ImageApiKey(SQLModel, table=True):
    user_id: int = DBField(primary_key=True)
    digest: str = DBField(index=True, unique=True)
    business_key: str
    created_at: datetime = DBField(default_factory=lambda: datetime.now(timezone.utc))


class ImagePostInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business: BusinessProfile | None = None
    inputs: dict = Field(default_factory=dict)
    brand: Brand | None = None
    topic: str = Field(default="", max_length=200)
    brief: CreativeBrief | None = None
    visual: VisualOptions = Field(default_factory=VisualOptions)
    references: list[ReferenceImage] = Field(default_factory=list, max_length=4)
    research_requested: bool = False
    feedback: str = Field(default="", max_length=2000)
    original: dict | None = None
    revision_mode: str = "both"


def session_user(request):
    from .app import require_user
    user = require_user(request)
    if not user or not user.is_active:
        raise HTTPException(401, "Sign in to an active workspace")
    return user


def token_user(request):
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer ") or len(authorization) > 200:
        raise HTTPException(401, "Use a workspace API token from /api-access")
    digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
    with get_session() as db:
        key = db.exec(select(ImageApiKey).where(ImageApiKey.digest == digest)).first()
        user = db.get(User, key.user_id) if key else None
    profile = _profile(user.id) if user else None
    if not key or not user or not user.is_active or not profile or key.business_key != _key(profile):
        raise HTTPException(401, "Invalid, revoked or outdated workspace token")
    return user, profile


@router.get("/api-access")
def api_access(request: Request):
    from .app import templates
    user = session_user(request)
    request.session["api_csrf"] = secrets.token_urlsafe(32)
    request.session["api_csrf_workspace"] = user.id
    with get_session() as db:
        key = db.get(ImageApiKey, user.id)
    return templates.TemplateResponse(request, "api_access.html", {"user": user, "key": key,
        "profile": _profile(user.id), "csrf": request.session["api_csrf"], "token": None},
        headers={"Cache-Control": "no-store"})


@router.post("/api-access")
def change_key(request: Request, csrf: str = Form(...), action: str = Form("rotate")):
    from .app import templates
    user = session_user(request)
    expected = request.session.get("api_csrf", "")
    origin = request.headers.get("origin")
    if (not expected or request.session.get("api_csrf_workspace") != user.id
            or not hmac.compare_digest(csrf, expected)
            or (origin and urlparse(origin).netloc != request.url.netloc)):
        raise HTTPException(403, "Use the API access form on Reachly")
    profile = _profile(user.id)
    if not profile or action not in {"rotate", "revoke"}:
        raise HTTPException(422, "Save a business profile and choose create or revoke")
    token = "reachly_" + secrets.token_urlsafe(36) if action == "rotate" else None
    with get_session() as db:
        key = db.get(ImageApiKey, user.id)
        if key:
            db.delete(key); db.flush()
        key = ImageApiKey(user_id=user.id, digest=hashlib.sha256(token.encode()).hexdigest(), business_key=_key(profile)) if token else None
        if key:
            db.add(key)
        db.commit()
    request.session["api_csrf"] = secrets.token_urlsafe(32)
    return templates.TemplateResponse(request, "api_access.html", {"user": user, "profile": profile,
        "key": key, "token": token, "csrf": request.session["api_csrf"]}, headers={"Cache-Control": "no-store"})


def owner(user):
    return f"personal-{user.id}"


def owned(request, job_id):
    user, profile = token_user(request)
    try:
        row = store.get(job_id, owner(user))
    except ValueError:
        row = None
    if not row or row["business"] != _key(profile):
        raise HTTPException(404, "Image post not found in this workspace")
    return user, profile, row


def provider_for(profile):
    values = decrypt_dict(profile.providers_vault) if profile.providers_vault else {}
    name = values.get("llm_provider") or profile.llm_provider
    if name not in {"gemini", "openai", "anthropic"} or not values.get(name + "_api_key") or not values.get("gemini_api_key"):
        raise HTTPException(422, "Add this workspace's text provider key and Gemini image key in Settings")
    defaults = {"gemini": "gemini-2.5-flash", "openai": "gpt-4o-mini", "anthropic": "claude-3-5-sonnet-latest"}
    return {"llm_provider": name, "llm_model": values.get("llm_model") or defaults[name],
            "image_model": values.get("gemini_image_model") or "gemini-3.1-flash-image",
            **{key: values.get(key, "") for key in ("gemini_api_key", "openai_api_key", "anthropic_api_key")}}


def build_payload(data, profile):
    values = decrypt_dict(profile.providers_vault) if profile.providers_vault else {}
    business = data.business or BusinessProfile(**{k: getattr(profile, k) for k in
        ("name", "website", "sector", "vision", "product_info", "brand_voice", "language")})
    if _key(business) != _key(profile):
        raise HTTPException(422, "Business name and website must match the selected workspace")
    # Saved inputs are used only when the caller omits inputs, so payloads are reproducible.
    facts = data.inputs if "inputs" in data.model_fields_set else {
        "goals": profile.goals, **{k: values.get(k, "") for k in ("project_notes", "research_notes", "performance_notes")}}
    if len(json.dumps(facts)) > 60000:
        raise HTTPException(422, "Keep combined input context within 60,000 characters")
    brand = {"colors": values.get("brand_colors", "").split(",") if values.get("brand_colors") else [],
             "theme": values.get("brand_theme", "")}
    # Only a logo owned by this business can be included.
    if values.get("brand_owner", "").casefold() == profile.name.casefold() and values.get("brand_logo_path"):
        logo = Path(values["brand_logo_path"])
        if logo.is_file() and logo.stat().st_size <= 2_000_000:
            brand["logo_base64"] = base64.b64encode(logo.read_bytes()).decode()
    if data.brand is not None:
        brand = data.brand.model_dump()
    payload = GenerationRequest(schema_version=4, business_id=_key(profile), business=business,
        public_facts=facts, source_version=hashlib.sha256(json.dumps({"business": business.model_dump(), "inputs": facts, "brand": brand}, sort_keys=True).encode()).hexdigest(),
        brand=brand, count=1, topic=data.topic, brief=data.brief, visual=data.visual,
        references=data.references, research_requested=data.research_requested,
        feedback=data.feedback, original=data.original, revision_mode=data.revision_mode)
    payload.check_scope()
    return payload


def execute(row, provider):
    # Atomic specific-job claim: simultaneous POST/GETs cannot repeat provider calls.
    with store.database() as db:
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute("UPDATE jobs SET state='running',updated=? WHERE id=? AND owner=? AND state='queued'",
                             (time.time(), row["id"], row["owner"]))
        if not changed.rowcount:
            return
    process(row, provider_override=provider)


def finished(task):
    _tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("Image-post background task stopped: %s", type(task.exception()).__name__)


def launch(row, profile):
    if row["state"] == "queued":
        task = asyncio.create_task(asyncio.to_thread(execute, row, provider_for(profile)))
        _tasks.add(task)
        task.add_done_callback(finished)
        return task
    return None


def response(row, include_image):
    data = store.response(row)
    prefix = f"/api/v1/image-posts/{row['id']}"
    data.update(status_url=prefix, audit_url=prefix + "/audit")
    for item in data.get("candidates", []):
        if item["state"] == "completed":
            item["image_url"] = prefix + "/image/" + item["id"]
            if include_image:
                path = store.root() / row["id"] / (str(uuid.UUID(item["id"])) + ".png")
                item["image_base64"] = base64.b64encode(path.read_bytes()).decode()
                item["mime_type"] = "image/png"
    return JSONResponse(data, status_code=202 if row["state"] in {"queued", "running"} else 200,
                        headers={"Cache-Control": "private, no-store"})


@router.post("/api/v1/image-posts")
async def create(request: Request, wait_seconds: int = Query(25, ge=0, le=90), include_image: bool = True):
    user, profile = token_user(request)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16_000_000:
            raise HTTPException(413, "Image post payload exceeds 16 MB")
    try:
        data = ImagePostInput.model_validate_json(body)
        payload = build_payload(data, profile)
        request_id = str(uuid.UUID(request.headers.get("Idempotency-Key", "")))
    except (ValueError, ValidationError):
        raise HTTPException(422, "Invalid image post payload or UUID Idempotency-Key")
    if payload.original:
        _, _, previous = owned(request, payload.original["job_id"])
        if not any(c["id"] == payload.original["candidate_id"] and c["state"] == "completed"
                   for c in json.loads(previous["result"]).get("candidates", [])):
            raise HTTPException(422, "Original candidate must be complete")
    # Validate keys before queueing, but never put credentials in the durable job payload.
    provider = provider_for(profile)
    try:
        if payload.revision_mode != "copy":
            validate_options(payload.visual, provider["image_model"])
    except (ValueError, OSError):
        raise HTTPException(422, "Requested resolution or layout font is unavailable for this workspace")
    try:
        row = store.submit(owner(user), request_id, payload.model_dump(), "personal-workspace", max_hourly_jobs=10)
    except OverflowError:
        raise HTTPException(429, "Workspace generation limit: ten jobs per hour")
    except ValueError:
        raise HTTPException(409, "Idempotency-Key already used with different inputs")
    task = launch(row, profile)
    if task and wait_seconds:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_seconds)
        except asyncio.TimeoutError:
            pass  # Work continues; poll the returned status URL with the same token.
    return response(store.get(row["id"], owner(user)), include_image)


@router.get("/api/v1/image-posts/{job_id}")
async def status(request: Request, job_id: str, include_image: bool = True):
    user, profile, row = owned(request, job_id)
    launch(row, profile)  # A queued job survives a web-process restart; no paid replay of running jobs.
    if row["state"] == "running":
        with store.database() as db:
            db.execute("UPDATE jobs SET state='needs_attention' WHERE id=? AND state='running' AND updated<?", (row["id"], time.time()-1800))
        row = store.get(job_id, owner(user))
    return response(row, include_image)


@router.get("/api/v1/image-posts/{job_id}/image/{candidate_id}")
def image(request: Request, job_id: str, candidate_id: str):
    _, _, row = owned(request, job_id)
    if not any(c["id"] == candidate_id and c["state"] == "completed" for c in json.loads(row["result"]).get("candidates", [])):
        raise HTTPException(404, "Image is unavailable or did not pass review")
    return FileResponse(store.root() / row["id"] / (str(uuid.UUID(candidate_id)) + ".png"), media_type="image/png",
                        headers={"Cache-Control": "private, no-store"})


@router.get("/api/v1/image-posts/{job_id}/audit")
def audit(request: Request, job_id: str):
    _, _, row = owned(request, job_id)
    folder = store.root() / row["id"]
    trace = folder / "text-prompts.json"
    return JSONResponse({"job_id": row["id"], "records": {p.stem: json.loads(p.read_text()) for p in folder.glob("*.audit.json")},
        "text_prompts": json.loads(trace.read_text()) if trace.is_file() else {"calls": []}}, headers={"Cache-Control": "private, no-store"})
