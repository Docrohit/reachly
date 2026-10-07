"""Owner-scoped business workspaces sharing one personal sign-in."""
import uuid

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select
from .db import User, BusinessProfileRow, get_session

router = APIRouter()


def account_owner(request):
    owner_id = request.session.get("user_id")
    with get_session() as session:
        owner = session.get(User, owner_id) if owner_id else None
    if not owner or owner.owner_user_id is not None:
        raise HTTPException(401, "Sign in with your personal Reachly account.")
    return owner


def create_workspace(owner_id, name, website, **profile_values):
    from urllib.parse import urlparse
    name = name.strip()
    if not name or len(name) > 160:
        raise ValueError("Use a business name between 1 and 160 characters.")
    if website and (urlparse(website).scheme not in ("https", "http") or not urlparse(website).hostname):
        raise ValueError("Provide a valid website URL.")
    with get_session() as session:
        owner = session.get(User, owner_id)
        if not owner or owner.owner_user_id is not None:
            raise ValueError("A personal account owner is required.")
        workspaces = session.exec(select(User).where(User.owner_user_id == owner_id)).all()
        if len(workspaces) >= 30:
            raise ValueError("This account already has 30 business workspaces.")
        # Early personal installs require a unique, non-null Telegram ID. A
        # namespaced non-Telegram value keeps that schema without binding a
        # workspace to another person's login or rebuilding the user table.
        workspace = User(owner_user_id=owner_id, auth_provider="workspace", username=name,
                         telegram_chat_id=f"workspace:{uuid.uuid4()}",
                         is_active=owner.is_active, plan=owner.plan, timezone=owner.timezone,
                         dry_run=True, scheduler_enabled=False)
        session.add(workspace); session.flush()
        profile = BusinessProfileRow(user_id=workspace.id, name=name, website=website or None, **profile_values)
        session.add(profile); session.commit(); session.refresh(workspace)
        return workspace


@router.get("/workspaces")
def workspaces(request: Request):
    from .app import current_user, templates
    owner = account_owner(request)
    with get_session() as session:
        accounts = session.exec(select(User).where((User.id == owner.id) | (User.owner_user_id == owner.id))).all()
        items = []
        for account in accounts:
            profile = session.exec(select(BusinessProfileRow).where(BusinessProfileRow.user_id == account.id)).first()
            items.append({"id": account.id, "name": profile.name if profile else "Personal workspace", "website": profile.website if profile else ""})
    return templates.TemplateResponse(request, "workspaces.html", {"user": current_user(request), "workspaces": items})


@router.post("/workspaces")
def add_workspace(request: Request, name: str = Form(...), website: str = Form("")):
    owner = account_owner(request)
    try:
        workspace = create_workspace(owner.id, name, website)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    request.session["workspace_id"] = workspace.id
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/workspaces/{workspace_id}/switch")
def switch_workspace(request: Request, workspace_id: int):
    owner = account_owner(request)
    with get_session() as session:
        workspace = session.get(User, workspace_id)
    if not workspace or (workspace.id != owner.id and workspace.owner_user_id != owner.id):
        raise HTTPException(404, "Workspace not found.")
    request.session["workspace_id"] = workspace.id
    return RedirectResponse("/studio", status_code=303)
