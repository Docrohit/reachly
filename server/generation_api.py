"""Authenticated business-scoped generation; no publishing side effects."""
import hmac
import json
import os
import re
import uuid
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from reachly import generation_store as store
from reachly.generation_config import configuration
from reachly.generation_contract import GenerationRequest

router = APIRouter(prefix="/api/v1/generation-jobs")


def business_allowed(owner, entry, business, organisation=None):
    if organisation:
        return (entry.get("organisation_provisioning") is True
            and re.fullmatch(r"HYC-[A-F0-9]{16}", business) is not None
            and store.organisation_registered(owner, organisation))
    return business in entry.get("business_ids", [])


def client(request):
    try:
        clients = configuration()["clients"]
    except (ValueError, KeyError, OSError):
        raise HTTPException(503, "Generation service is not configured")
    owner = request.headers.get("X-Reachly-Client", "")
    entry = clients.get(owner, {})
    secret = os.getenv(entry.get("token_env", ""), "")
    if not secret or not hmac.compare_digest(request.headers.get("Authorization", "").encode(), ("Bearer " + secret).encode()):
        raise HTTPException(401, "Invalid generation credentials")
    return owner, entry


def owned_job(request, job_id):
    owner, entry = client(request)
    try:
        row = store.get(job_id, owner)
    except ValueError:
        row = None
    if not row or not business_allowed(owner, entry, row["business"], json.loads(row["payload"]).get("organisation_id")):
        raise HTTPException(404, "Generation job not found")
    return row


@router.post("/organisations")
async def register_organisation(request: Request):
    owner, entry = client(request)
    if entry.get("organisation_provisioning") is not True:
        raise HTTPException(403, "Organisation provisioning is not enabled for this service client")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 4096:
            raise HTTPException(413, "Organisation registration is too large")
    try:
        data = json.loads(body)
        if not isinstance(data, dict) or set(data) != {"organisation_id"}:
            raise ValueError("Invalid registration")
        organisation = data["organisation_id"]
        if not isinstance(organisation, str) or not re.fullmatch(r"ORG-[A-F0-9]{16}", organisation):
            raise ValueError("Invalid organisation ID")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "A valid organisation ID is required")
    store.register_organisation(owner, organisation)
    return {"organisation_id": organisation, "state": "registered"}


@router.post("", status_code=202)
async def create(request: Request):
    owner, entry = client(request)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16_000_000:
            raise HTTPException(413, "Generation request too large")
    try:
        payload = GenerationRequest.model_validate_json(body)
        payload.check_scope()
        request_id = str(uuid.UUID(request.headers.get("Idempotency-Key", "")))
    except (ValueError, ValidationError):
        raise HTTPException(422, "Invalid generation input, evidence scope or request ID")
    if not business_allowed(owner, entry, payload.business_id, payload.organisation_id):
        raise HTTPException(403, "Business is not provisioned for this client")
    if payload.original:
        previous = owned_job(request, payload.original.get("job_id", ""))
        if previous["business"] != payload.business_id:
            raise HTTPException(403, "Original candidate belongs to another business")
        candidates = json.loads(previous["result"]).get("candidates", [])
        if not any(c.get("id") == payload.original.get("candidate_id") and c.get("state") == "completed" for c in candidates):
            raise HTTPException(422, "Original candidate is not complete")
    try:
        encoded = payload.model_dump()
        if payload.schema_version == 1:
            encoded.pop("operation", None)
            encoded.pop("brief", None)
        if payload.organisation_id is None:
            # Preserve the digest of pre-onboarding requests on an in-flight replay.
            encoded.pop("organisation_id")
        row = store.submit(owner, request_id, encoded, entry["provider"],
            max_hourly_jobs=int(entry.get("max_hourly_jobs", 20)))
    except PermissionError:
        raise HTTPException(403, "Clinic organisation binding is not authorised")
    except OverflowError:
        raise HTTPException(429, "Business generation hourly limit reached")
    except ValueError:
        raise HTTPException(409, "Request ID already used with different inputs")
    return store.response(row)


@router.get("/{job_id}")
def status(request: Request, job_id: str):
    return store.response(owned_job(request, job_id))


@router.get("/{job_id}/assets/{candidate_id}")
def asset(request: Request, job_id: str, candidate_id: str):
    row = owned_job(request, job_id)
    candidates = json.loads(row["result"]).get("candidates", [])
    item = next((c for c in candidates if c.get("id") == candidate_id and c.get("state") == "completed"), None)
    if not item:
        raise HTTPException(404, "Image is not ready")
    path = store.root() / row["id"] / (str(uuid.UUID(candidate_id)) + ".png")
    if not path.is_file():
        raise HTTPException(404, "Image is not available")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/{job_id}/audit")
def audit(request: Request, job_id: str):
    row = owned_job(request, job_id)
    folder = store.root() / row["id"]
    records = {p.stem: json.loads(p.read_text()) for p in folder.glob("*.audit.json")}
    trace = folder / "text-prompts.json"
    return JSONResponse({"job_id": row["id"], "state": row["state"], "records": records,
            "text_prompts": json.loads(trace.read_text()) if trace.is_file() else {"calls": []}}, headers={"Cache-Control": "private, no-store"})
