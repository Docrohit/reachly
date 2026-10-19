"""Channels: connect each personal project to its Facebook Page, Instagram and X
accounts, publish drafts to several channels, and run a 24-hour autopilot.

Connections use the owner's own OAuth consent on personal apps (REACHLY_META_*,
REACHLY_X_*). Tokens are stored encrypted per project in PlatformCredRow and
never reach the browser. Each channel of a draft is attempted at most once
unless the platform definitely refused it; uncertain outcomes are never retried.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import threading
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import Column, DateTime, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, SQLModel, select

from reachly.models import GeneratedPost, Platform
from .crypto import decrypt_dict, encrypt_dict
from .db import BusinessProfileRow, PlatformCredRow, PostLogRow, User, get_session
from .settings import get_settings

router = APIRouter()
logger = logging.getLogger("reachly.channels")

CHANNELS = {"facebook": "Facebook Page", "instagram": "Instagram", "twitter": "X"}
META_SCOPES = ("pages_show_list,pages_read_engagement,pages_manage_posts,business_management,"
               "instagram_basic,instagram_content_publish")
X_SCOPES = "tweet.read tweet.write users.read media.write offline.access"
X_API = "https://api.x.com/2"
STATE_TTL = timedelta(minutes=15)
RETRY_AFTER = timedelta(hours=3)      # autopilot backoff after an attempt
STALE_RUN = timedelta(hours=1)        # a "running" status older than this crashed
DRAFT_MAX_AGE = timedelta(days=14)    # autopilot ignores older drafts
NOTICES = {
    "connected": "Connected.", "disconnected": "Disconnected.", "saved": "Saved.",
    "working": "Working on it. Refresh in a minute to see the result.",
    "published": "Publishing finished. See the results under the draft.",
    "discarded": "Draft discarded.", "project": "Project created. Add its AI provider key in Settings if you did not copy one.",
    "invited": "Invitation sent. The client signs in with that email and a code.",
    "invite_saved": "Client added, but the invitation email could not be sent. Ask them to sign in at /login with that email.",
    "client_removed": "Client access removed.", "reviewed": "Thanks. Your review was saved.",
}
ERRORS = {
    "cancelled": "The sign-in was cancelled or expired. Try again and finish within 15 minutes.",
    "not_configured": "That connection is not configured on this server yet.",
    "no_page": "No Facebook Page with posting permission was shared. Reconnect and select the Page.",
    "provider": "The platform did not complete the connection. Try again.",
    "busy": "Publishing is in progress for this account. Try again when it finishes.",
    "invite_invalid": "Enter a valid client email address.",
    "invite_used": "That email already has Reachly access. Remove it first or use another email.",
}
_x_refresh_lock = threading.Lock()


class ChannelOAuthState(SQLModel, table=True):
    state: str = Field(primary_key=True)
    owner_id: int = Field(index=True)
    workspace_id: int
    provider: str                       # meta | x | pick
    sealed: str = ""                    # encrypted JSON (PKCE verifier, Page choices)
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=False), nullable=False))


class ChannelPublication(SQLModel, table=True):
    id: str = Field(primary_key=True)   # "<draft id>:<platform>", one attempt per channel
    user_id: int = Field(index=True)
    draft_id: str = Field(index=True)
    platform: str
    trigger: str = "manual"             # manual | autopilot
    state: str = "sending"              # sending | published | failed | check_platform
    permalink: str = ""
    detail: str = ""
    # Naive UTC throughout, matching PostLogRow, so times compare directly.
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False), nullable=False))


class AutopilotSetting(SQLModel, table=True):
    user_id: int = Field(primary_key=True)
    enabled: bool = False
    platforms: str = ""                 # comma-separated channel keys
    interval_hours: int = 24
    last_attempt_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))
    status: str = "idle"                # idle | running | published | failed | skipped
    detail: str = ""


# ---- scope helpers -------------------------------------------------------
def _owner(request: Request) -> User:
    from .workspaces import account_owner
    return account_owner(request)


def _workspace(owner: User, workspace_id: int) -> User:
    with get_session() as session:
        workspace = session.get(User, workspace_id)
    if not workspace or (workspace.id != owner.id and workspace.owner_user_id != owner.id):
        raise HTTPException(404, "Project not found.")
    return workspace


def _projects(owner: User) -> list[User]:
    with get_session() as session:
        return list(session.exec(select(User).where(
            (User.id == owner.id) | (User.owner_user_id == owner.id)).order_by(User.id)).all())


def _actor(request: Request):
    """The owner (all projects) or an invited client (one project)."""
    from .accounts import current_actor
    return current_actor(request)


def _project_for(actor, workspace_id: int) -> User:
    if workspace_id not in actor.workspace_ids:
        raise HTTPException(404, "Project not found.")
    with get_session() as session:
        workspace = session.get(User, workspace_id)
    if not workspace:
        raise HTTPException(404, "Project not found.")
    return workspace


def _same_origin(request: Request) -> None:
    from urllib.parse import urlparse
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.url.netloc:
        raise HTTPException(403, "Use the form on Reachly to perform this action.")


def _back(notice: str = "", error: str = "", anchor: int | None = None, home: str = "/channels") -> RedirectResponse:
    query = urlencode({k: v for k, v in (("notice", notice), ("error", error)) if v})
    return RedirectResponse(home + ("?" + query if query else "") + (f"#p{anchor}" if anchor else ""), status_code=303)


def provider_status() -> dict:
    s = get_settings()
    return {"meta": bool(s.meta_app_id and s.meta_app_secret), "x": bool(s.x_client_id and s.x_client_secret)}


def _redirect_uri(provider: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/channels/oauth/{provider}/callback"


def _graph(path: str) -> str:
    return f"https://graph.facebook.com/{get_settings().meta_graph_version}/{path.lstrip('/')}"


def _http(method: str, url: str, **kwargs) -> dict:
    """Bounded provider call; errors never include tokens or provider bodies."""
    try:
        response = requests.request(method, url, timeout=25, **kwargs)
    except requests.RequestException:
        raise ValueError("provider unreachable") from None
    if not response.ok:
        logger.warning("Channel provider call failed: %s %s -> HTTP %s", method, url.split("?")[0], response.status_code)
        raise ValueError(f"provider HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise ValueError("provider returned unreadable JSON") from None


# ---- connections -----------------------------------------------------------
def connections(workspace_id: int) -> dict:
    with get_session() as session:
        rows = session.exec(select(PlatformCredRow).where(PlatformCredRow.user_id == workspace_id)).all()
    found = {}
    for row in rows:
        if row.platform not in CHANNELS or row.mode != "api" or not row.vault:
            continue
        data = decrypt_dict(row.vault)
        if not (data.get("access_token") or data.get("oauth2_token") or data.get("access_token_secret")):
            continue
        account = data.get("account") or ("@" + data["verified_username"] if data.get("verified_username") else "connected")
        found[row.platform] = {"account": account, "via": data.get("connected_via", "keys"),
                               "status": data.get("status", "active")}
    return found


def _bind(workspace_id: int, platform: str, data: dict) -> None:
    """Replace a channel's credentials entirely (old keys must not linger)."""
    with get_session() as session:
        busy = session.exec(select(ChannelPublication).where(
            ChannelPublication.user_id == workspace_id, ChannelPublication.platform == platform,
            ChannelPublication.state == "sending")).first()
        if busy:
            raise ValueError("busy")
        row = session.exec(select(PlatformCredRow).where(
            PlatformCredRow.user_id == workspace_id, PlatformCredRow.platform == platform)).first()
        row = row or PlatformCredRow(user_id=workspace_id, platform=platform)
        row.mode = "api"
        row.vault = encrypt_dict({**data, "connected_via": "oauth", "connected_at": datetime.utcnow().isoformat()})
        session.add(row); session.commit()


def _new_state(actor, workspace_id: int, provider: str, sealed: dict | None = None) -> str:
    state = secrets.token_urlsafe(32)
    with get_session() as session:
        session.add(ChannelOAuthState(state=state, owner_id=actor.owner_id, workspace_id=workspace_id, provider=provider,
                                      sealed=encrypt_dict({**(sealed or {}), "actor": actor.key}),
                                      expires_at=datetime.utcnow() + STATE_TTL))
        session.commit()
    return state


def _state_owner_matches(actor, row: ChannelOAuthState) -> dict:
    sealed = decrypt_dict(row.sealed) if row.sealed else {}
    if row.owner_id != actor.owner_id or sealed.get("actor", f"owner:{row.owner_id}") != actor.key \
            or row.workspace_id not in actor.workspace_ids or row.expires_at < datetime.utcnow():
        raise ValueError("cancelled")
    return sealed


def _pop_state(actor, provider: str, state: str) -> tuple[User, dict]:
    """Single-use state bound to the signed-in person (owner or client) who started the flow."""
    with get_session() as session:
        row = session.get(ChannelOAuthState, str(state or "")[:100])
        if row:
            session.delete(row); session.commit()
    if not row or row.provider != provider:
        raise ValueError("cancelled")
    sealed = _state_owner_matches(actor, row)
    return _project_for(actor, row.workspace_id), sealed


@router.get("/channels/{workspace_id}/connect/{provider}")
def connect(request: Request, workspace_id: int, provider: str):
    actor = _actor(request)
    workspace = _project_for(actor, workspace_id)
    if provider not in ("meta", "x"):
        raise HTTPException(404, "Unknown connection.")
    if not provider_status()[provider]:
        return _back(error="not_configured", anchor=workspace.id, home=actor.home)
    s = get_settings()
    if provider == "meta":
        state = _new_state(actor, workspace.id, "meta")
        params = {"client_id": s.meta_app_id, "redirect_uri": _redirect_uri("meta"), "state": state, "response_type": "code"}
        if s.meta_login_config_id:
            params["config_id"] = s.meta_login_config_id
        else:
            params["scope"] = META_SCOPES
        return RedirectResponse(f"https://www.facebook.com/{s.meta_graph_version}/dialog/oauth?" + urlencode(params), status_code=303)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = _new_state(actor, workspace.id, "x", {"verifier": verifier})
    params = {"response_type": "code", "client_id": s.x_client_id, "redirect_uri": _redirect_uri("x"),
              "scope": X_SCOPES, "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    return RedirectResponse("https://x.com/i/oauth2/authorize?" + urlencode(params), status_code=303)


def _connect_page(workspace_id: int, page: dict) -> None:
    _bind(workspace_id, "facebook", {"access_token": page["access_token"], "page_id": str(page["id"]),
                                     "account": page.get("name") or "Facebook Page",
                                     "page_url": f"https://www.facebook.com/{page['id']}"})
    ig = page.get("instagram_business_account") or {}
    if ig.get("id"):
        _bind(workspace_id, "instagram", {"access_token": page["access_token"], "user_id": str(ig["id"]),
                                          "page_id": str(page["id"]), "account": "@" + (ig.get("username") or str(ig["id"]))})


@router.get("/channels/oauth/meta/callback")
def meta_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    actor = _actor(request)
    back = lambda **kw: _back(home=actor.home, **kw)  # noqa: E731
    try:
        workspace, _ = _pop_state(actor, "meta", state)
    except ValueError:
        return back(error="cancelled")
    if error or not code:
        return back(error="cancelled", anchor=workspace.id)
    s = get_settings()
    app = {"client_id": s.meta_app_id, "client_secret": s.meta_app_secret}
    try:
        short = _http("GET", _graph("oauth/access_token"), params={**app, "redirect_uri": _redirect_uri("meta"), "code": code})["access_token"]
        # Page tokens derived from a long-lived user token do not expire on a timer.
        long = _http("GET", _graph("oauth/access_token"), params={**app, "grant_type": "fb_exchange_token", "fb_exchange_token": short})["access_token"]
        from reachly.platforms.facebook import appsecret_proof
        pages = _http("GET", _graph("me/accounts"), params={
            "fields": "id,name,access_token,tasks,instagram_business_account{id,username}", "limit": 100,
            "access_token": long, **appsecret_proof(long, s.meta_app_secret)}).get("data", [])
    except (ValueError, KeyError, TypeError):
        return back(error="provider", anchor=workspace.id)
    pages = [p for p in pages if p.get("access_token") and str(p.get("id", "")).isdigit()
             and ("tasks" not in p or "CREATE_CONTENT" in p["tasks"])]
    if not pages:
        return back(error="no_page", anchor=workspace.id)
    if len(pages) == 1:
        try:
            _connect_page(workspace.id, pages[0])
        except ValueError:
            return back(error="busy", anchor=workspace.id)
        return back(notice="connected", anchor=workspace.id)
    pick = _new_state(actor, workspace.id, "pick", {"pages": pages})
    return RedirectResponse(f"/channels/{workspace.id}/meta/pick?pick={pick}", status_code=303)


def _pick_pages(actor, workspace: User, pick: str) -> list[dict]:
    with get_session() as session:
        row = session.get(ChannelOAuthState, str(pick or "")[:100])
    try:
        if not row or row.workspace_id != workspace.id or row.provider != "pick":
            raise ValueError("expired")
        return _state_owner_matches(actor, row).get("pages", [])
    except ValueError:
        raise HTTPException(410, "Page selection expired. Connect Facebook again.") from None


@router.get("/channels/{workspace_id}/meta/pick")
def meta_pick(request: Request, workspace_id: int, pick: str = ""):
    from .app import templates
    actor = _actor(request)
    workspace = _project_for(actor, workspace_id)
    pages = [{"id": p["id"], "name": p.get("name", ""), "instagram": (p.get("instagram_business_account") or {}).get("username")}
             for p in _pick_pages(actor, workspace, pick)]
    return templates.TemplateResponse(request, "channels_pick.html", {
        "user": workspace if actor.kind == "owner" else None, "client": actor.email, "home": actor.home,
        "project": _profile_name(workspace.id), "workspace_id": workspace.id, "pages": pages, "pick": pick})


@router.post("/channels/{workspace_id}/meta/pick")
def meta_pick_save(request: Request, workspace_id: int, pick: str = Form(...), page_id: str = Form(...)):
    _same_origin(request)
    actor = _actor(request)
    workspace = _project_for(actor, workspace_id)
    page = next((p for p in _pick_pages(actor, workspace, pick) if str(p["id"]) == page_id), None)
    if not page:
        raise HTTPException(422, "Choose one of the Pages you authorised.")
    with get_session() as session:
        row = session.get(ChannelOAuthState, pick)
        if row:
            session.delete(row); session.commit()
    try:
        _connect_page(workspace.id, page)
    except ValueError:
        return _back(error="busy", anchor=workspace.id, home=actor.home)
    return _back(notice="connected", anchor=workspace.id, home=actor.home)


@router.get("/channels/oauth/x/callback")
def x_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    actor = _actor(request)
    back = lambda **kw: _back(home=actor.home, **kw)  # noqa: E731
    try:
        workspace, sealed = _pop_state(actor, "x", state)
    except ValueError:
        return back(error="cancelled")
    if error or not code:
        return back(error="cancelled", anchor=workspace.id)
    s = get_settings()
    try:
        token = _http("POST", f"{X_API}/oauth2/token", auth=(s.x_client_id, s.x_client_secret), data={
            "code": code, "grant_type": "authorization_code", "redirect_uri": _redirect_uri("x"),
            "code_verifier": sealed["verifier"], "client_id": s.x_client_id})
        me = _http("GET", f"{X_API}/users/me", headers={"Authorization": f"Bearer {token['access_token']}"})["data"]
        username, user_id = str(me["username"]), str(me["id"])
        if not user_id.isdigit():
            raise ValueError("bad identity")
        _bind(workspace.id, "twitter", {
            "oauth2_token": token["access_token"], "oauth2_refresh_token": token.get("refresh_token", ""),
            "oauth2_expires_at": (datetime.utcnow() + timedelta(seconds=int(token.get("expires_in", 7200)))).isoformat(),
            "account": "@" + username, "expected_account": username,
            "verified_user_id": user_id, "verified_username": username})
    except ValueError as exc:
        return back(error="busy" if str(exc) == "busy" else "provider", anchor=workspace.id)
    except (KeyError, TypeError):
        return back(error="provider", anchor=workspace.id)
    return back(notice="connected", anchor=workspace.id)


def refresh_x_token(row: PlatformCredRow) -> PlatformCredRow:
    """Refresh an expiring OAuth 2.0 X token. X rotates refresh tokens, so refresh
    under a lock and re-read the row; a stale refresh token would be rejected."""
    data = decrypt_dict(row.vault) if row.vault else {}
    if not data.get("oauth2_refresh_token") or not _expiring(data):
        return row
    s = get_settings()
    with _x_refresh_lock:
        with get_session() as session:
            current = session.get(PlatformCredRow, row.id)
            if not current or not current.vault:
                return row
            data = decrypt_dict(current.vault)
            if not data.get("oauth2_refresh_token") or not _expiring(data):
                return current
            try:
                token = _http("POST", f"{X_API}/oauth2/token", auth=(s.x_client_id, s.x_client_secret), data={
                    "grant_type": "refresh_token", "refresh_token": data["oauth2_refresh_token"], "client_id": s.x_client_id})
                data.update(oauth2_token=token["access_token"], status="active",
                            oauth2_refresh_token=token.get("refresh_token", data["oauth2_refresh_token"]),
                            oauth2_expires_at=(datetime.utcnow() + timedelta(seconds=int(token.get("expires_in", 7200)))).isoformat())
            except (ValueError, KeyError, TypeError):
                logger.warning("X token refresh failed for project %s; reconnect required.", row.user_id)
                data["status"] = "reconnect"
            current.vault = encrypt_dict(data)
            session.add(current); session.commit(); session.refresh(current)
            return current


def _expiring(data: dict) -> bool:
    try:
        return datetime.fromisoformat(data.get("oauth2_expires_at", "")) < datetime.utcnow() + timedelta(minutes=5)
    except ValueError:
        return True


@router.post("/channels/{workspace_id}/{platform}/disconnect")
def disconnect(request: Request, workspace_id: int, platform: str):
    _same_origin(request)
    actor = _actor(request)
    workspace = _project_for(actor, workspace_id)
    if platform not in CHANNELS:
        raise HTTPException(404, "Unknown channel.")
    with get_session() as session:
        if session.exec(select(ChannelPublication).where(ChannelPublication.user_id == workspace.id,
                        ChannelPublication.platform == platform, ChannelPublication.state == "sending")).first():
            return _back(error="busy", anchor=workspace.id, home=actor.home)
        row = session.exec(select(PlatformCredRow).where(PlatformCredRow.user_id == workspace.id,
                                                         PlatformCredRow.platform == platform)).first()
        if row:
            session.delete(row); session.commit()
    return _back(notice="disconnected", anchor=workspace.id, home=actor.home)


# ---- drafts, generation and publishing --------------------------------------
def _profile_row(workspace_id: int):
    with get_session() as session:
        return session.exec(select(BusinessProfileRow).where(BusinessProfileRow.user_id == workspace_id)).first()


def _profile_name(workspace_id: int) -> str:
    profile = _profile_row(workspace_id)
    return profile.name if profile else "Personal workspace"


def generate_draft(workspace: User, topic: str | None = None):
    """Generate one image post as a Studio draft for this project."""
    from reachly.visual import Layout, VisualOptions
    from .orchestrator import build_agent_for_user
    from .studio import StudioDraft, _key
    if not workspace.is_active:
        raise ValueError("Activate your Reachly account before generating.")
    profile = _profile_row(workspace.id)
    agent = build_agent_for_user(workspace) if profile else None
    if not agent:
        raise ValueError("Save this project's business profile and AI provider key in Settings first.")
    try:
        post = agent.build_post(theme=(topic or "").strip()[:500] or None, attach_image=True,
                                visual_options=VisualOptions(aspect_ratio="1:1", image_size="1K", layout=Layout()))
        if not post.media:
            raise ValueError("Image generation did not complete. Check the image provider key.")
        draft = StudioDraft(user_id=workspace.id, business_key=_key(profile), content=post.model_dump_json())
        with get_session() as session:
            session.add(draft); session.commit(); session.refresh(draft)
        return draft
    finally:
        agent.close()


def _definite_failure(error: str) -> bool:
    from reachly.platforms.facebook import REJECTED
    return (error or "").startswith(REJECTED)


def _set_publication(pub_id: str, state: str, permalink: str = "", detail: str = "") -> None:
    with get_session() as session:
        row = session.get(ChannelPublication, pub_id)
        row.state, row.permalink, row.detail, row.updated_at = state, permalink or "", detail[:500], datetime.utcnow()
        session.add(row); session.commit()


def _claim_channel(workspace_id: int, draft_id: str, platform: str, trigger: str) -> Optional[str]:
    """One attempt per draft and channel; only a definite refusal may be retried."""
    pub_id = f"{draft_id}:{platform}"
    try:
        with get_session() as session:
            session.add(ChannelPublication(id=pub_id, user_id=workspace_id, draft_id=draft_id, platform=platform, trigger=trigger))
            session.commit()
        return pub_id
    except IntegrityError:
        with get_session() as session:
            result = session.execute(update(ChannelPublication).where(
                ChannelPublication.id == pub_id, ChannelPublication.state == "failed",
            ).values(state="sending", trigger=trigger, detail="", updated_at=datetime.utcnow()))
            session.commit()
        return pub_id if result.rowcount == 1 else None


def publish_draft(workspace: User, draft_id: str, platforms: list[str], trigger: str = "manual") -> dict:
    """Publish one draft to the chosen connected channels. Returns {platform: state}."""
    from .orchestrator import _record_results, build_agent_for_user
    from .studio import StudioDraft, _key
    from .x_engagement import guarded_send
    with get_session() as session:
        workspace = session.get(User, workspace.id)
    if not workspace.is_active:
        raise ValueError("Activate your Reachly account before publishing.")
    if workspace.dry_run:
        raise ValueError("Turn on Live publishing for this project first.")
    profile = _profile_row(workspace.id)
    with get_session() as session:
        draft = session.get(StudioDraft, draft_id)
        managed = session.exec(select(ChannelPublication).where(ChannelPublication.draft_id == draft_id)).first()
    if not profile or not draft or draft.user_id != workspace.id or draft.business_key != _key(profile):
        raise ValueError("That draft does not belong to this project's current business.")
    if draft.state != "draft" and not managed:
        raise ValueError("This draft was already handled in Studio. Check its result there.")
    connected = connections(workspace.id)
    targets = [p for p in dict.fromkeys(platforms) if p in CHANNELS and p in connected]
    if not targets:
        raise ValueError("Choose at least one connected channel.")
    post = GeneratedPost.model_validate_json(draft.content)
    with get_session() as session:
        session.execute(update(StudioDraft).where(StudioDraft.id == draft.id).values(state="publishing"))
        session.commit()
    outcome: dict[str, str] = {}
    agent = build_agent_for_user(workspace)
    try:
        for platform in targets:
            pub_id = _claim_channel(workspace.id, draft.id, platform, trigger)
            if not pub_id:
                outcome[platform] = "skipped"
                continue
            target = Platform(platform)
            if platform == "instagram" and not post.media:
                _set_publication(pub_id, "failed", detail="Instagram needs an image post.")
                outcome[platform] = "failed"
                continue
            creds = agent.platforms.get(target) if agent else None
            if not creds or not creds.enabled:
                _set_publication(pub_id, "failed", detail="Reconnect this channel.")
                outcome[platform] = "failed"
                continue
            try:
                if platform == "twitter":
                    result = guarded_send(workspace, post.for_platform(target), expected_credentials=creds,
                                          publish=lambda: agent._publish(post, platforms=[target])[target])
                else:
                    result = agent._publish(post, platforms=[target])[target]
                _record_results(workspace.id, {target: result})
                if result.ok and result.permalink:
                    state, detail = "published", ""
                elif result.ok:
                    state, detail = "check_platform", "Posted without a link. Check the account."
                elif _definite_failure(result.error or ""):
                    state, detail = "failed", (result.error or "")[len("rejected: "):]
                else:
                    state, detail = "check_platform", "Outcome unconfirmed. Check the account before retrying."
            except ValueError as exc:
                text = str(exc)
                definite = "already attempted" in text or "daily limit" in text or "dry-run" in text
                state, detail = ("failed" if definite else "check_platform"), text
                result = None
            except Exception:  # noqa: BLE001
                logger.warning("Channel publish interrupted for project %s on %s", workspace.id, platform)
                state, detail, result = "check_platform", "Publishing was interrupted. Check the account before retrying.", None
            _set_publication(pub_id, state, result.permalink if result and state == "published" else "", detail)
            outcome[platform] = state
    finally:
        if agent:
            agent.close()
        with get_session() as session:
            pubs = session.exec(select(ChannelPublication).where(ChannelPublication.draft_id == draft.id)).all()
            states = {p.state for p in pubs}
            final = "published" if "published" in states else "check_platform" if "check_platform" in states else "failed"
            session.execute(update(StudioDraft).where(StudioDraft.id == draft.id).values(state=final))
            session.commit()
    return outcome


# ---- autopilot -------------------------------------------------------------
def last_published_at(workspace_id: int) -> Optional[datetime]:
    with get_session() as session:
        rows = session.exec(select(PostLogRow.created_at).where(
            PostLogRow.user_id == workspace_id, PostLogRow.ok == True,  # noqa: E712
            PostLogRow.permalink.is_not(None), PostLogRow.permalink != "(dry-run)",
        ).order_by(PostLogRow.created_at.desc()).limit(1)).all()
    return rows[0] if rows else None


def autopilot_setting(workspace_id: int) -> AutopilotSetting:
    with get_session() as session:
        row = session.get(AutopilotSetting, workspace_id)
        if not row:
            row = AutopilotSetting(user_id=workspace_id)
            session.add(row); session.commit(); session.refresh(row)
        return row


def _queue(workspace_id: int, need_image: bool) -> list:
    """Unpublished drafts never attempted by Channels, oldest first, last 14 days."""
    from .studio import StudioDraft, _key
    profile = _profile_row(workspace_id)
    if not profile:
        return []
    since = datetime.utcnow() - DRAFT_MAX_AGE
    with get_session() as session:
        attempted = set(session.exec(select(ChannelPublication.draft_id).where(ChannelPublication.user_id == workspace_id)).all())
        from .accounts import DraftReview
        # A client asking for changes holds the draft back from autopilot.
        attempted |= set(session.exec(select(DraftReview.draft_id).where(
            DraftReview.user_id == workspace_id, DraftReview.state == "changes")).all())
        drafts = session.exec(select(StudioDraft).where(
            StudioDraft.user_id == workspace_id, StudioDraft.business_key == _key(profile),
            StudioDraft.state == "draft").order_by(StudioDraft.created_at)).all()
    queue = []
    for draft in drafts:
        created = draft.created_at.replace(tzinfo=None) if draft.created_at.tzinfo else draft.created_at
        if draft.id in attempted or created < since:
            continue
        if need_image and not GeneratedPost.model_validate_json(draft.content).media:
            continue
        queue.append(draft)
    return queue


def due_reason(workspace: User, setting: AutopilotSetting, now: datetime) -> Optional[str]:
    """None when an autopilot run is due, otherwise why it is not."""
    if not setting.enabled:
        return "Autopilot is off."
    if not workspace.is_active or workspace.dry_run:
        return "Live publishing is off for this project."
    if not [p for p in setting.platforms.split(",") if p in connections(workspace.id)]:
        return "No autopilot channel is connected."
    last = last_published_at(workspace.id)
    if last and now - last < timedelta(hours=setting.interval_hours):
        return f"Last post was less than {setting.interval_hours} hours ago."
    if setting.last_attempt_at and now - setting.last_attempt_at < RETRY_AFTER and setting.status != "published":
        return "Waiting before trying again after the last attempt."
    return None


def run_cycle(workspace_id: int, *, force: bool = False, publish: bool = True, topic: str = "",
              trigger: str = "autopilot") -> str:
    """Publish the next queued draft (generating one when the queue is empty).
    Without force it only runs when the project's autopilot is due."""
    now = datetime.utcnow()
    with get_session() as session:
        workspace = session.get(User, workspace_id)
    setting = autopilot_setting(workspace_id)
    if not force:
        reason = due_reason(workspace, setting, now)
        if reason:
            return reason
    # Claim the project so the scheduler and a click never run it twice.
    with get_session() as session:
        claim = session.execute(update(AutopilotSetting).where(
            AutopilotSetting.user_id == workspace_id,
            (AutopilotSetting.status != "running") | (AutopilotSetting.last_attempt_at < now - STALE_RUN),
        ).values(status="running", detail="Working…", last_attempt_at=now))
        session.commit()
    if claim.rowcount != 1:
        return "Already running."
    status, detail = "failed", ""
    try:
        platforms = [p for p in (setting.platforms.split(",") if setting.platforms else list(CHANNELS)) if p in connections(workspace_id)]
        if publish and not platforms:
            raise ValueError("Connect a channel and choose it for autopilot first.")
        queue = [] if (topic or not publish) else _queue(workspace_id, need_image="instagram" in platforms)
        draft = queue[0] if queue else generate_draft(workspace, topic)
        if not publish:
            status, detail = "idle", "New draft ready to review."
        else:
            outcome = publish_draft(workspace, draft.id, platforms, trigger=trigger)
            status = "published" if "published" in outcome.values() else "failed"
            detail = ", ".join(f"{CHANNELS[p]}: {s.replace('_', ' ')}" for p, s in outcome.items())
    except ValueError as exc:
        detail = str(exc)
    except Exception:  # noqa: BLE001
        logger.exception("Autopilot run failed for project %s", workspace_id)
        detail = "Generation or publishing failed. Check provider keys and connections."
    with get_session() as session:
        row = session.get(AutopilotSetting, workspace_id)
        row.status, row.detail = status, detail[:500]
        session.add(row); session.commit()
    return detail


def autopilot_tick() -> None:
    """Scheduler job: run every due project in turn."""
    with get_session() as session:
        ids = session.exec(select(AutopilotSetting.user_id).where(AutopilotSetting.enabled == True)).all()  # noqa: E712
    for workspace_id in ids:
        try:
            run_cycle(workspace_id)
        except Exception:  # noqa: BLE001
            logger.exception("Autopilot tick failed for project %s", workspace_id)


def _background(target, *args, **kwargs) -> None:
    threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True).start()


# ---- pages -----------------------------------------------------------------
def _project_view(workspace: User) -> dict:
    from .accounts import clients_for
    from .studio import StudioDraft, _key
    profile = _profile_row(workspace.id)
    setting = autopilot_setting(workspace.id)
    linked = connections(workspace.id)
    drafts = []
    if profile:
        with get_session() as session:
            rows = session.exec(select(StudioDraft).where(
                StudioDraft.user_id == workspace.id, StudioDraft.business_key == _key(profile),
                StudioDraft.state != "discarded").order_by(StudioDraft.created_at.desc()).limit(4)).all()
            pubs = session.exec(select(ChannelPublication).where(
                ChannelPublication.draft_id.in_([d.id for d in rows]))).all() if rows else []
        from .accounts import reviews_for
        reviews = reviews_for([r.id for r in rows])
        for row in rows:
            post = GeneratedPost.model_validate_json(row.content)
            drafts.append({"row": row, "post": post, "pubs": [p for p in pubs if p.draft_id == row.id],
                           "review": reviews.get(row.id)})
    last = last_published_at(workspace.id)
    now = datetime.utcnow()
    return {
        "id": workspace.id, "name": profile.name if profile else "Personal workspace",
        "website": profile.website if profile else "", "has_profile": bool(profile),
        "live": workspace.is_active and not workspace.dry_run, "connections": linked,
        "autopilot": setting, "autopilot_channels": [p for p in setting.platforms.split(",") if p],
        "last_published": last, "next_due": (last + timedelta(hours=setting.interval_hours)) if last else None,
        "due_note": due_reason(workspace, setting, now), "drafts": drafts,
        "queue": len(_queue(workspace.id, need_image="instagram" in setting.platforms)),
        "clients": clients_for(workspace.id),
    }


@router.get("/channels")
def channels_page(request: Request, notice: str = "", error: str = ""):
    from .app import current_user, templates
    owner = _owner(request)
    return templates.TemplateResponse(request, "channels.html", {
        "user": current_user(request), "projects": [_project_view(w) for w in _projects(owner)],
        "providers": provider_status(), "channels": CHANNELS, "now": datetime.utcnow(),
        "notice": NOTICES.get(notice, ""), "error": ERRORS.get(error, ""),
    })


@router.post("/channels/projects")
def add_project(request: Request, name: str = Form(...), website: str = Form(""), about: str = Form(""),
                copy_keys_from: int = Form(0)):
    from .workspaces import create_workspace
    _same_origin(request)
    owner = _owner(request)
    if len(about) > 5000:
        raise HTTPException(422, "Keep the description within 5,000 characters.")
    try:
        workspace = create_workspace(owner.id, name, website.strip(), product_info=about.strip() or None)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if copy_keys_from:
        source = _profile_row(_workspace(owner, copy_keys_from).id)
        keys = decrypt_dict(source.providers_vault) if source and source.providers_vault else {}
        copied = {k: v for k, v in keys.items() if k.endswith("_api_key") or k in ("llm_provider", "llm_model", "image_provider")}
        if copied:
            with get_session() as session:
                target = session.exec(select(BusinessProfileRow).where(BusinessProfileRow.user_id == workspace.id)).first()
                target.providers_vault = encrypt_dict(copied)
                session.add(target); session.commit()
    return _back(notice="project", anchor=workspace.id)


@router.post("/channels/{workspace_id}/live")
def set_live(request: Request, workspace_id: int, live: str = Form("off")):
    _same_origin(request)
    workspace = _workspace(_owner(request), workspace_id)
    with get_session() as session:
        row = session.get(User, workspace.id)
        row.dry_run = live != "on"
        session.add(row); session.commit()
    return _back(notice="saved", anchor=workspace.id)


@router.post("/channels/{workspace_id}/autopilot")
def save_autopilot(request: Request, workspace_id: int, enabled: str = Form("off"), platforms: list[str] = Form(default=[])):
    _same_origin(request)
    workspace = _workspace(_owner(request), workspace_id)
    chosen = [p for p in dict.fromkeys(platforms) if p in CHANNELS]
    autopilot_setting(workspace.id)
    with get_session() as session:
        row = session.get(AutopilotSetting, workspace.id)
        row.enabled, row.platforms = enabled == "on", ",".join(chosen)
        if row.status not in ("running",):
            row.status, row.detail = "idle", ""
        session.add(row); session.commit()
    return _back(notice="saved", anchor=workspace.id)


@router.post("/channels/{workspace_id}/run")
def run_now(request: Request, workspace_id: int, mode: str = Form("publish"), topic: str = Form("")):
    _same_origin(request)
    workspace = _workspace(_owner(request), workspace_id)
    if len(topic) > 500:
        raise HTTPException(422, "Keep the topic within 500 characters.")
    _background(run_cycle, workspace.id, force=True, publish=mode != "generate", topic=topic, trigger="manual")
    return _back(notice="working", anchor=workspace.id)


@router.post("/channels/{workspace_id}/drafts/{draft_id}/publish")
def publish_one(request: Request, workspace_id: int, draft_id: str, platforms: list[str] = Form(default=[])):
    _same_origin(request)
    workspace = _workspace(_owner(request), workspace_id)
    try:
        publish_draft(workspace, draft_id, platforms, trigger="manual")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return _back(notice="published", anchor=workspace.id)


@router.post("/channels/{workspace_id}/drafts/{draft_id}/discard")
def discard(request: Request, workspace_id: int, draft_id: str):
    from .studio import StudioDraft
    _same_origin(request)
    workspace = _workspace(_owner(request), workspace_id)
    with get_session() as session:
        session.execute(update(StudioDraft).where(StudioDraft.id == draft_id, StudioDraft.user_id == workspace.id,
                                                  StudioDraft.state == "draft").values(state="discarded"))
        session.commit()
    return _back(notice="discarded", anchor=workspace.id)


@router.get("/channels/{workspace_id}/drafts/{draft_id}/media")
def draft_media(request: Request, workspace_id: int, draft_id: str):
    from .app import _resolve_user_media, _user_agent_dir
    from .studio import StudioDraft
    workspace = _workspace(_owner(request), workspace_id)
    with get_session() as session:
        draft = session.get(StudioDraft, draft_id)
    if not draft or draft.user_id != workspace.id:
        raise HTTPException(404, "Draft not found.")
    post = GeneratedPost.model_validate_json(draft.content)
    path = _resolve_user_media(_user_agent_dir(workspace.id), post.media.local_path) if post.media else None
    if not path:
        raise HTTPException(404, "Draft media is unavailable.")
    return FileResponse(path, media_type=post.media.mime_type)
