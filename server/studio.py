"""Personal content studio: business inputs, grounded research, drafts and results."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import Field, SQLModel, select
from sqlalchemy import update

from reachly.generation_worker import research_business
from reachly.models import GeneratedPost, Platform
from reachly.storage import History
from .crypto import decrypt_dict, encrypt_dict
from .db import BusinessProfileRow, get_session
from .orchestrator import build_agent_for_user, _record_results

router = APIRouter()
logger = logging.getLogger("reachly.studio")


class StudioDraft(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: int = Field(index=True)
    business_key: str = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content: str
    state: str = "draft"
    platform: str = ""
    result: str = ""


def _user(request):
    from .app import require_user
    user = require_user(request)
    if not user:
        raise HTTPException(401, "Please sign in to Reachly.")
    return user


def _profile(user_id):
    with get_session() as session:
        return session.exec(select(BusinessProfileRow).where(BusinessProfileRow.user_id == user_id)).first()


def _key(profile):
    import hashlib
    return hashlib.sha256((profile.name + "|" + (profile.website or "")).encode()).hexdigest()[:16]


def _draft(user_id, draft_id):
    profile = _profile(user_id)
    with get_session() as session:
        draft = session.get(StudioDraft, draft_id)
    if not profile or not draft or draft.user_id != user_id or draft.business_key != _key(profile):
        raise HTTPException(404, "Draft not found for this business.")
    return draft


def _active_agent(user):
    if not user.is_active:
        raise HTTPException(403, "Activate your Reachly account before generating or publishing.")
    agent = build_agent_for_user(user)
    if not agent:
        raise HTTPException(422, "Save your business profile and provider keys first.")
    return agent


@router.get("/studio")
def studio(request: Request):
    from .app import templates
    user = _user(request)
    profile = _profile(user.id)
    inputs = decrypt_dict(profile.providers_vault) if profile and profile.providers_vault else {}
    with get_session() as session:
        drafts = session.exec(select(StudioDraft).where(
            StudioDraft.user_id == user.id,
            StudioDraft.business_key == (_key(profile) if profile else ""),
        ).order_by(StudioDraft.created_at.desc()).limit(30)).all()
    items = [{"row": d, "post": GeneratedPost.model_validate_json(d.content)} for d in drafts]
    return templates.TemplateResponse(request, "studio.html", {
        "user": user, "profile": profile, "drafts": items,
        "project_notes": inputs.get("project_notes", ""),
        "research_notes": inputs.get("research_notes", ""),
        "performance_notes": inputs.get("performance_notes", ""),
    })


@router.post("/studio/inputs")
def save_inputs(request: Request, project_notes: str = Form(""), research_notes: str = Form(""), performance_notes: str = Form("")):
    user = _user(request)
    if any(len(v) > 30000 for v in (project_notes, research_notes, performance_notes)):
        raise HTTPException(422, "Keep each input within 30,000 characters.")
    with get_session() as session:
        profile = session.exec(select(BusinessProfileRow).where(BusinessProfileRow.user_id == user.id)).first()
        if not profile:
            raise HTTPException(422, "Save your business profile first.")
        data = decrypt_dict(profile.providers_vault) if profile.providers_vault else {}
        data.update(project_notes=project_notes, research_notes=research_notes, performance_notes=performance_notes)
        profile.providers_vault = encrypt_dict(data)
        session.add(profile); session.commit()
    return RedirectResponse("/studio", status_code=303)


@router.post("/studio/research")
def research(request: Request):
    user = _user(request)
    profile = _profile(user.id)
    agent = _active_agent(user)
    try:
        if not agent.settings.gemini_api_key:
            raise HTTPException(422, "Add your Gemini API key in Settings to run online research.")
        evidence = research_business(SimpleNamespace(business=agent.business, business_id=_key(profile)), {
            "gemini_api_key": agent.settings.gemini_api_key,
        })
        text = json.dumps(evidence, ensure_ascii=False, indent=2)
        with get_session() as session:
            current = session.get(BusinessProfileRow, profile.id)
            if not current or _key(current) != _key(profile):
                raise HTTPException(409, "The business changed while research ran. Run it again for the selected business.")
            data = decrypt_dict(current.providers_vault) if current.providers_vault else {}
            data["research_notes"] = text[:30000]
            current.providers_vault = encrypt_dict(data)
            session.add(current); session.commit()
    except HTTPException:
        raise
    except Exception:
        logger.warning("Research failed for user %s", user.id)
        raise HTTPException(502, "Research failed. Check your provider access; no research was invented or saved.")
    finally:
        agent.close()
    return RedirectResponse("/studio", status_code=303)


@router.post("/studio/generate")
def generate(request: Request, topic: str = Form(""), with_image: str = Form("off")):
    user = _user(request)
    profile = _profile(user.id)
    if len(topic) > 500:
        raise HTTPException(422, "Keep the topic within 500 characters.")
    agent = _active_agent(user)
    try:
        post = agent.build_post(theme=topic.strip() or None, attach_image=with_image == "on")
        if with_image == "on" and not post.media:
            raise HTTPException(502, "Image generation did not complete. Check the image provider before retrying.")
        with get_session() as session:
            session.add(StudioDraft(user_id=user.id, business_key=_key(profile), content=post.model_dump_json()))
            session.commit()
    except HTTPException:
        raise
    except Exception:
        logger.warning("Draft generation failed for user %s", user.id)
        raise HTTPException(502, "Generation failed. Check your provider keys and configuration.")
    finally:
        agent.close()
    return RedirectResponse("/studio", status_code=303)


@router.get("/studio/{draft_id}/media")
def draft_media(request: Request, draft_id: str):
    from .app import _user_agent_dir, _resolve_user_media
    user = _user(request)
    draft = _draft(user.id, draft_id)
    post = GeneratedPost.model_validate_json(draft.content)
    if not post.media:
        raise HTTPException(404, "No media for this draft.")
    path = _resolve_user_media(_user_agent_dir(user.id), post.media.local_path)
    if not path:
        raise HTTPException(404, "Draft media is unavailable.")
    return FileResponse(path, media_type=post.media.mime_type)


@router.post("/studio/{draft_id}/publish")
def publish(request: Request, draft_id: str, platform: str = Form(...), confirm: str = Form("")):
    user = _user(request)
    draft = _draft(user.id, draft_id)
    if confirm != "publish" or user.dry_run:
        raise HTTPException(422, "Enable Live mode in Settings and confirm publication to the selected account.")
    try:
        target = Platform(platform)
    except ValueError:
        raise HTTPException(422, "Unknown platform.")
    agent = _active_agent(user)
    try:
        if _key(agent.business) != draft.business_key:
            raise HTTPException(409, "The business changed. Review this draft in its original workspace.")
        creds = agent.platforms.get(target)
        if not creds or not creds.enabled:
            raise HTTPException(422, "Connect and enable that platform in Settings first.")
        post = GeneratedPost.model_validate_json(draft.content)
        if target == Platform.youtube and (not post.media or post.media.kind != "video"):
            raise HTTPException(422, "YouTube requires a video draft.")
        if target in (Platform.instagram, Platform.medium) and not post.media:
            raise HTTPException(422, "This platform requires media; generate an image draft first.")
        # Claim once before contacting a platform. Unknown outcomes are never
        # retried automatically because that could publish duplicates.
        with get_session() as session:
            result = session.execute(update(StudioDraft).where(
                StudioDraft.id == draft.id, StudioDraft.user_id == user.id,
                StudioDraft.state == "draft",
            ).values(state="publishing", platform=platform))
            session.commit()
            if result.rowcount != 1:
                raise HTTPException(409, "This draft already has a publishing attempt. Check its result on the platform.")
        try:
            results = agent._publish(post, platforms=[target])
            _record_results(user.id, results)
            outcome = results.get(target)
            # Browser providers may lack a permalink; surface that separately.
            state = "published" if outcome and outcome.ok and outcome.permalink else "check_platform"
            detail = outcome.permalink if state == "published" else "Publication needs verification on the selected platform. Do not retry until checked."
        except Exception:
            state, detail = "check_platform", "Publishing was interrupted. Check the platform before retrying."
        with get_session() as session:
            row = session.get(StudioDraft, draft.id)
            row.state, row.result = state, detail
            session.add(row); session.commit()
    finally:
        agent.close()
    return RedirectResponse("/studio", status_code=303)


@router.get("/analytics")
def analytics(request: Request):
    from .app import templates, _user_agent_dir
    user = _user(request)
    history = History(_user_agent_dir(user.id))
    try:
        rows = history.recent_platform_posts(limit=50)
        summary = history.analytics_summary(days=30, limit=20)
    finally:
        history.close()
    return templates.TemplateResponse(request, "analytics.html", {"user": user, "rows": rows, "summary": summary})


@router.post("/analytics/{post_id}")
def save_analytics(request: Request, post_id: int, impressions: int | None = Form(None), likes: int | None = Form(None), comments: int | None = Form(None), shares: int | None = Form(None)):
    from .app import _user_agent_dir
    user = _user(request)
    if any(v is not None and (v < 0 or v > 10**12) for v in (impressions, likes, comments, shares)):
        raise HTTPException(422, "Metrics must be non-negative counts.")
    history = History(_user_agent_dir(user.id))
    try:
        row = history._conn.execute("SELECT ok, permalink FROM posts WHERE id=?", (post_id,)).fetchone()
        if not row or not row[0] or row[1] == "(dry-run)":
            raise HTTPException(404, "Published post not found in this business's history.")
        history.record_analytics(post_id, impressions=impressions, likes=likes, comments=comments, shares=shares, note="Metrics entered from the platform by the account owner")
    finally:
        history.close()
    return RedirectResponse("/analytics", status_code=303)
