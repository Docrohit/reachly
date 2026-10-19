"""Email-code sign-in for the owner and invited clients, and the client portal.

The owner links a sign-in email from an existing session (proved with a code).
The owner can invite a client by email to one project; a client signs in with a
code and sees only that project: its channels, drafts and their own reviews.
No passwords are stored. Codes are six digits, HMAC-hashed, single use, valid
for ten minutes, with five attempts and five codes per email per hour.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import Column, DateTime, update
from sqlmodel import Field, SQLModel, select

from reachly.models import GeneratedPost
from .db import User, get_session
from .settings import get_settings

router = APIRouter()
logger = logging.getLogger("reachly.accounts")

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
HOURLY_CODES = 5
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,185}\.[A-Za-z]{2,24}$")


def _naive_dt(nullable: bool = False):
    return Column(DateTime(timezone=False), nullable=nullable)


class EmailIdentity(SQLModel, table=True):
    email: str = Field(primary_key=True)          # lower-case
    user_id: int = Field(index=True)              # the account owner
    role: str = "owner"                           # owner | client
    workspace_id: Optional[int] = Field(default=None, index=True)  # clients: their one project
    invited_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=_naive_dt())


class EmailCode(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    email: str = Field(index=True)
    purpose: str                                  # login | link
    code_hash: str
    user_id: Optional[int] = None                 # link: the owner proving the email
    attempts: int = 0
    consumed: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=_naive_dt())
    expires_at: datetime = Field(sa_column=_naive_dt())


class DraftReview(SQLModel, table=True):
    draft_id: str = Field(primary_key=True)
    user_id: int = Field(index=True)              # project (workspace) id
    state: str                                    # approved | changes
    note: str = ""
    reviewer: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=_naive_dt())


# ---- who is signed in ------------------------------------------------------
@dataclass(frozen=True)
class Actor:
    kind: str                                     # owner | client
    owner_id: int
    key: str
    workspace_ids: frozenset
    email: str = ""

    @property
    def home(self) -> str:
        return "/channels" if self.kind == "owner" else "/client"


def current_actor(request: Request) -> Actor:
    if request.session.get("user_id"):
        from .workspaces import account_owner
        owner = account_owner(request)
        with get_session() as session:
            ids = session.exec(select(User.id).where((User.id == owner.id) | (User.owner_user_id == owner.id))).all()
        return Actor("owner", owner.id, f"owner:{owner.id}", frozenset(ids))
    client = client_identity(request)
    if client:
        return Actor("client", client.user_id, f"client:{client.email}", frozenset({client.workspace_id}), client.email)
    raise HTTPException(401, "Please sign in to Reachly.")


def client_identity(request: Request) -> Optional[EmailIdentity]:
    """The signed-in client, re-checked on every request so removal takes effect."""
    email = request.session.get("client_email")
    if not email:
        return None
    with get_session() as session:
        identity = session.get(EmailIdentity, email)
        project = session.get(User, identity.workspace_id) if identity and identity.workspace_id else None
    if not identity or identity.role != "client" or identity.workspace_id != request.session.get("client_workspace") \
            or not project or (project.id != identity.user_id and project.owner_user_id != identity.user_id):
        request.session.clear()
        return None
    return identity


# ---- codes and email -------------------------------------------------------
def normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address.")
    return email


def email_enabled() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


def send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not email_enabled():
        raise ValueError("Email is not configured on this server.")
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = s.smtp_from, to, subject
    message.set_content(body)
    context = ssl.create_default_context()
    if s.smtp_port == 465:
        smtp = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20, context=context)
    else:
        smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
        smtp.starttls(context=context)
    with smtp:
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(message)


def _hash(email: str, code: str) -> str:
    return hmac.new(get_settings().session_secret.encode(), f"{email}|{code}".encode(), hashlib.sha256).hexdigest()


def issue_code(email: str, purpose: str, user_id: int | None = None) -> bool:
    """Create and email a code. Returns False when the hourly limit is reached."""
    now = datetime.utcnow()
    with get_session() as session:
        recent = session.exec(select(EmailCode).where(EmailCode.email == email,
                                                      EmailCode.created_at > now - timedelta(hours=1))).all()
        if len(recent) >= HOURLY_CODES:
            return False
        session.execute(update(EmailCode).where(EmailCode.email == email, EmailCode.purpose == purpose,
                                                EmailCode.consumed == False).values(consumed=True))  # noqa: E712
        code = f"{secrets.randbelow(10 ** 6):06d}"
        session.add(EmailCode(email=email, purpose=purpose, code_hash=_hash(email, code), user_id=user_id,
                              expires_at=now + CODE_TTL))
        session.commit()
    what = "sign in to" if purpose == "login" else "confirm this email for"
    send_email(email, f"Your Reachly code: {code}",
               f"Your code to {what} Reachly is {code}.\n\nIt expires in 10 minutes. "
               "If you did not ask for it, ignore this email.\n")
    return True


def check_code(email: str, purpose: str, code: str) -> Optional[EmailCode]:
    code = (code or "").strip()
    with get_session() as session:
        row = session.exec(select(EmailCode).where(
            EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.consumed == False,  # noqa: E712
            EmailCode.expires_at > datetime.utcnow()).order_by(EmailCode.created_at.desc())).first()
        if not row:
            return None
        row.attempts += 1
        ok = row.attempts <= MAX_ATTEMPTS and len(code) == 6 and hmac.compare_digest(row.code_hash, _hash(email, code))
        if ok or row.attempts >= MAX_ATTEMPTS:
            row.consumed = True
        session.add(row); session.commit(); session.refresh(row)
        return row if ok else None


# ---- sign-in ---------------------------------------------------------------
def _login_page(request: Request, *, error: str = "", email: str = "", sent: bool = False, status: int = 200):
    from .app import settings, templates
    return templates.TemplateResponse(request, "login.html", {
        "bot": settings.telegram_bot_username, "error": error or None, "telegram_enabled": settings.telegram_login_enabled,
        "email_enabled": email_enabled(), "email": email, "email_sent": sent}, status_code=status)


@router.post("/auth/email/start")
def email_start(request: Request, email: str = Form(...)):
    try:
        email = normalize_email(email)
    except ValueError as exc:
        return _login_page(request, error=str(exc), status=422)
    if not email_enabled():
        return _login_page(request, error="Email sign-in is not available yet.", email=email, status=503)
    with get_session() as session:
        identity = session.get(EmailIdentity, email)
    if identity:
        try:
            issue_code(email, "login")
        except Exception:  # noqa: BLE001
            logger.warning("Sign-in email could not be sent.")
            return _login_page(request, error="The code email could not be sent. Try again shortly.", email=email, status=502)
    # Same reply either way: whether an email can sign in is not disclosed.
    return _login_page(request, email=email, sent=True)


@router.post("/auth/email/verify")
def email_verify(request: Request, email: str = Form(...), code: str = Form(...)):
    try:
        email = normalize_email(email)
    except ValueError as exc:
        return _login_page(request, error=str(exc), status=422)
    with get_session() as session:
        identity = session.get(EmailIdentity, email)
        owner = session.get(User, identity.user_id) if identity else None
    if not identity or not owner or owner.owner_user_id is not None or not check_code(email, "login", code):
        return _login_page(request, error="Invalid or expired code.", email=email, sent=True, status=401)
    request.session.clear()
    if identity.role == "owner":
        request.session["user_id"], request.session["auth_provider"] = owner.id, "email"
        return RedirectResponse("/channels", status_code=303)
    request.session["client_email"], request.session["client_workspace"] = email, identity.workspace_id
    return RedirectResponse("/client", status_code=303)


# ---- owner: sign-in email --------------------------------------------------
def _owner(request: Request) -> User:
    from .workspaces import account_owner
    return account_owner(request)


def _same_origin(request: Request) -> None:
    from .channels import _same_origin as check
    check(request)


@router.get("/account/email")
def account_email(request: Request, sent: str = "", error: str = "", done: str = ""):
    from .app import current_user, templates
    owner = _owner(request)
    with get_session() as session:
        linked = session.exec(select(EmailIdentity).where(EmailIdentity.user_id == owner.id,
                                                          EmailIdentity.role == "owner")).first()
    messages = {"used": "That email is already used by another sign-in.", "invalid": "Enter a valid email address.",
                "code": "Invalid or expired code.", "limit": "Too many codes. Try again in an hour.",
                "send": "The email could not be sent. Check the SMTP settings.", "off": "Email is not configured on this server."}
    return templates.TemplateResponse(request, "account_email.html", {
        "user": current_user(request), "linked": linked.email if linked else "", "sent": sent,
        "error": messages.get(error, ""), "done": bool(done), "enabled": email_enabled()})


@router.post("/account/email/start")
def account_email_start(request: Request, email: str = Form(...)):
    _same_origin(request)
    owner = _owner(request)
    try:
        email = normalize_email(email)
    except ValueError:
        return RedirectResponse("/account/email?error=invalid", status_code=303)
    if not email_enabled():
        return RedirectResponse("/account/email?error=off", status_code=303)
    with get_session() as session:
        existing = session.get(EmailIdentity, email)
    if existing and not (existing.role == "owner" and existing.user_id == owner.id):
        return RedirectResponse("/account/email?error=used", status_code=303)
    try:
        if not issue_code(email, "link", user_id=owner.id):
            return RedirectResponse("/account/email?error=limit", status_code=303)
    except Exception:  # noqa: BLE001
        logger.warning("Link email could not be sent.")
        return RedirectResponse("/account/email?error=send", status_code=303)
    from urllib.parse import quote
    return RedirectResponse(f"/account/email?sent={quote(email)}", status_code=303)


@router.post("/account/email/confirm")
def account_email_confirm(request: Request, email: str = Form(...), code: str = Form(...)):
    _same_origin(request)
    owner = _owner(request)
    try:
        email = normalize_email(email)
    except ValueError:
        return RedirectResponse("/account/email?error=invalid", status_code=303)
    row = check_code(email, "link", code)
    if not row or row.user_id != owner.id:
        from urllib.parse import quote
        return RedirectResponse(f"/account/email?sent={quote(email)}&error=code", status_code=303)
    with get_session() as session:
        existing = session.get(EmailIdentity, email)
        if existing and not (existing.role == "owner" and existing.user_id == owner.id):
            return RedirectResponse("/account/email?error=used", status_code=303)
        for old in session.exec(select(EmailIdentity).where(EmailIdentity.user_id == owner.id, EmailIdentity.role == "owner")).all():
            if old.email != email:
                session.delete(old)
        if not existing:
            session.add(EmailIdentity(email=email, user_id=owner.id, role="owner"))
        session.commit()
    return RedirectResponse("/account/email?done=1", status_code=303)


# ---- owner: client invitations ---------------------------------------------
def clients_for(workspace_id: int) -> list[str]:
    with get_session() as session:
        return [i.email for i in session.exec(select(EmailIdentity).where(
            EmailIdentity.workspace_id == workspace_id, EmailIdentity.role == "client").order_by(EmailIdentity.email)).all()]


@router.post("/channels/{workspace_id}/clients")
def invite_client(request: Request, workspace_id: int, email: str = Form(...)):
    from .channels import _back, _profile_name, _workspace
    _same_origin(request)
    owner = _owner(request)
    workspace = _workspace(owner, workspace_id)
    try:
        email = normalize_email(email)
    except ValueError:
        return _back(error="invite_invalid", anchor=workspace.id)
    with get_session() as session:
        if session.get(EmailIdentity, email):
            return _back(error="invite_used", anchor=workspace.id)
        session.add(EmailIdentity(email=email, user_id=owner.id, role="client", workspace_id=workspace.id, invited_by=owner.id))
        session.commit()
    base = get_settings().public_base_url.rstrip("/")
    try:
        send_email(email, f"You're invited to review {_profile_name(workspace.id)} on Reachly",
                   f"You've been invited to review social media posts for {_profile_name(workspace.id)} on Reachly.\n\n"
                   f"Sign in at {base}/login with this email address ({email}). We'll email you a 6-digit code; no password needed.\n\n"
                   "There you can connect your Facebook Page, Instagram and X accounts and approve posts or ask for changes.\n")
    except Exception:  # noqa: BLE001
        logger.warning("Invitation email could not be sent for project %s.", workspace.id)
        return _back(notice="invite_saved", anchor=workspace.id)
    return _back(notice="invited", anchor=workspace.id)


@router.post("/channels/{workspace_id}/clients/remove")
def remove_client(request: Request, workspace_id: int, email: str = Form(...)):
    from .channels import _back, _workspace
    _same_origin(request)
    workspace = _workspace(_owner(request), workspace_id)
    with get_session() as session:
        identity = session.get(EmailIdentity, (email or "").strip().lower())
        if identity and identity.role == "client" and identity.workspace_id == workspace.id:
            session.delete(identity); session.commit()
    return _back(notice="client_removed", anchor=workspace.id)


# ---- client portal ---------------------------------------------------------
def reviews_for(draft_ids: list[str]) -> dict:
    if not draft_ids:
        return {}
    with get_session() as session:
        return {r.draft_id: r for r in session.exec(select(DraftReview).where(DraftReview.draft_id.in_(draft_ids))).all()}


def _client(request: Request) -> EmailIdentity:
    identity = client_identity(request)
    if not identity:
        raise HTTPException(401, "Please sign in with the email you were invited with.")
    return identity


@router.get("/client")
def client_portal(request: Request, notice: str = "", error: str = ""):
    from .app import templates
    from .channels import CHANNELS, ERRORS, NOTICES, _project_view, provider_status
    identity = _client(request)
    with get_session() as session:
        workspace = session.get(User, identity.workspace_id)
    project = _project_view(workspace)
    return templates.TemplateResponse(request, "client.html", {
        "user": None, "client": identity.email, "p": project, "channels": CHANNELS, "providers": provider_status(),
        "notice": NOTICES.get(notice, ""), "error": ERRORS.get(error, "")})


def _client_draft(identity: EmailIdentity, draft_id: str):
    from .studio import StudioDraft
    with get_session() as session:
        draft = session.get(StudioDraft, draft_id)
    if not draft or draft.user_id != identity.workspace_id or draft.state == "discarded":
        raise HTTPException(404, "Post not found.")
    return draft


@router.post("/client/drafts/{draft_id}/review")
def client_review(request: Request, draft_id: str, decision: str = Form(...), note: str = Form("")):
    _same_origin(request)
    identity = _client(request)
    draft = _client_draft(identity, draft_id)
    if decision not in ("approved", "changes") or len(note) > 2000:
        raise HTTPException(422, "Choose approve or request changes (notes up to 2,000 characters).")
    with get_session() as session:
        row = session.get(DraftReview, draft.id) or DraftReview(draft_id=draft.id, user_id=identity.workspace_id, state=decision)
        row.state, row.note, row.reviewer, row.updated_at = decision, note.strip(), identity.email, datetime.utcnow()
        session.add(row); session.commit()
    return RedirectResponse("/client?notice=reviewed", status_code=303)


@router.get("/client/drafts/{draft_id}/media")
def client_media(request: Request, draft_id: str):
    from .app import _resolve_user_media, _user_agent_dir
    identity = _client(request)
    draft = _client_draft(identity, draft_id)
    post = GeneratedPost.model_validate_json(draft.content)
    path = _resolve_user_media(_user_agent_dir(identity.workspace_id), post.media.local_path) if post.media else None
    if not path:
        raise HTTPException(404, "Image unavailable.")
    return FileResponse(path, media_type=post.media.mime_type)
