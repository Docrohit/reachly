"""Reachly SaaS web app (FastAPI).

Routes:
  /                       landing page
  /login                  OTP login (Telegram)
  /auth/send-code         POST -> sends OTP via Telegram bot
  /auth/verify            POST -> verifies OTP, starts session
  /dashboard              the user's control panel
  /dashboard/profile      POST -> save business profile + provider keys
  /dashboard/platform     POST -> save one platform's credentials
  /dashboard/settings     POST -> schedule / dry-run / image toggle
  /dashboard/run-now      POST -> generate + post immediately
  /billing                upgrade page (Stripe optional)
  /billing/checkout       POST -> Stripe Checkout session
  /billing/webhook        POST -> Stripe webhook (activates account)
  /install                self-host install package + license (paid)
  /media/<file>           serves generated media (needed by Instagram API mode)
"""
from __future__ import annotations

import logging
import secrets
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import select
from starlette.middleware.sessions import SessionMiddleware

from .crypto import encrypt_dict
from .db import (
    BusinessProfileRow,
    PlatformCredRow,
    PostLogRow,
    User,
    get_session,
    init_db,
)
from .orchestrator import run_user_now, start_scheduler
from .settings import get_settings
from .telegram_bot import generate_and_send_otp, start_bot_thread, verify_otp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("reachly.app")

settings = get_settings()
BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Reachly")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)

media_path = Path(settings.media_dir)
media_path.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_path)), name="media")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    start_bot_thread()
    start_scheduler()


# ---- helpers ----------------------------------------------------------
def current_user(request: Request) -> User | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    with get_session() as session:
        return session.get(User, uid)


def require_user(request: Request) -> User | None:
    return current_user(request)


# ---- public pages -----------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse(
        request,
        "landing.html",
        {"bot": settings.telegram_bot_username, "user": current_user(request)},
    )


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request, "login.html", {"bot": settings.telegram_bot_username, "error": None}
    )


@app.post("/auth/send-code")
def send_code(handle: str = Form(...)):
    ok, msg = generate_and_send_otp(handle)
    return JSONResponse({"ok": ok, "message": msg})


@app.post("/auth/verify")
def verify(request: Request, handle: str = Form(...), code: str = Form(...)):
    ok, user_id = verify_otp(handle, code)
    if not ok:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"bot": settings.telegram_bot_username, "error": "Invalid or expired code."},
            status_code=401,
        )
    request.session["user_id"] = user_id
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# ---- dashboard --------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with get_session() as session:
        profile = session.exec(
            select(BusinessProfileRow).where(BusinessProfileRow.user_id == user.id)
        ).first()
        creds = session.exec(
            select(PlatformCredRow).where(PlatformCredRow.user_id == user.id)
        ).all()
        logs = session.exec(
            select(PostLogRow).where(PostLogRow.user_id == user.id)
            .order_by(PostLogRow.id.desc()).limit(20)
        ).all()
    cred_modes = {c.platform: c.mode for c in creds}
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user, "profile": profile,
            "cred_modes": cred_modes, "logs": logs, "settings": settings,
        },
    )


@app.post("/dashboard/profile")
def save_profile(
    request: Request,
    name: str = Form(...),
    website: str = Form(""),
    sector: str = Form(""),
    vision: str = Form(""),
    product_info: str = Form(""),
    brand_voice: str = Form("Confident, helpful, and human. No hype."),
    content_themes: str = Form(""),
    default_hashtags: str = Form(""),
    language: str = Form("English"),
    llm_provider: str = Form("gemini"),
    image_provider: str = Form("gemini"),
    video_provider: str = Form("none"),
    gemini_api_key: str = Form(""),
    openai_api_key: str = Form(""),
    anthropic_api_key: str = Form(""),
    hygaar_base_url: str = Form(""),
    hygaar_api_token: str = Form(""),
    goals: str = Form(""),
    context_repo: str = Form(""),
    posting_style: str = Form("thought_leader"),
):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    providers = {
        k: v for k, v in {
            "gemini_api_key": gemini_api_key,
            "openai_api_key": openai_api_key,
            "anthropic_api_key": anthropic_api_key,
            "hygaar_base_url": hygaar_base_url,
            "hygaar_api_token": hygaar_api_token,
        }.items() if v
    }

    with get_session() as session:
        row = session.exec(
            select(BusinessProfileRow).where(BusinessProfileRow.user_id == user.id)
        ).first()
        if not row:
            row = BusinessProfileRow(user_id=user.id)
        row.name, row.website, row.sector = name, website or None, sector or None
        row.vision, row.product_info = vision or None, product_info or None
        row.brand_voice = brand_voice
        row.content_themes, row.default_hashtags = content_themes, default_hashtags
        row.language = language
        row.llm_provider, row.image_provider, row.video_provider = (
            llm_provider, image_provider, video_provider
        )
        row.goals = goals
        row.context_repo = context_repo or None
        row.posting_style = posting_style
        # Merge provider keys: keep old ones if a field was left blank.
        existing = {}
        if row.providers_vault:
            from .crypto import decrypt_dict
            existing = decrypt_dict(row.providers_vault)
        existing.update(providers)
        row.providers_vault = encrypt_dict(existing)
        session.add(row)
        session.commit()
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/dashboard/platform")
def save_platform(
    request: Request,
    platform: str = Form(...),
    mode: str = Form("off"),
    # twitter
    oauth2_token: str = Form(""),
    login_identifier: str = Form(""),
    # linkedin
    access_token: str = Form(""),
    person_urn: str = Form(""),
    ig_user_id: str = Form(""),
    email: str = Form(""),
    # shared
    username: str = Form(""),
    password: str = Form(""),
):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if platform not in {"twitter", "linkedin", "instagram"} or mode not in {"off", "api", "browser"}:
        return JSONResponse({"error": "invalid platform settings"}, status_code=400)

    secrets_map = {
        k: v for k, v in {
            "oauth2_token": oauth2_token,
            "login_identifier": login_identifier,
            "access_token": access_token,
            "person_urn": person_urn,
            "user_id": ig_user_id,
            "email": email,
            "username": username,
            "password": password,
        }.items() if v
    }

    with get_session() as session:
        row = session.exec(
            select(PlatformCredRow)
            .where(PlatformCredRow.user_id == user.id)
            .where(PlatformCredRow.platform == platform)
        ).first()
        if not row:
            row = PlatformCredRow(user_id=user.id, platform=platform)
        row.mode = mode
        existing = {}
        if row.vault:
            from .crypto import decrypt_dict
            existing = decrypt_dict(row.vault)
        existing.update(secrets_map)
        row.vault = encrypt_dict(existing)
        session.add(row)
        session.commit()
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/dashboard/settings")
def save_settings(
    request: Request,
    post_time: str = Form("09:30"),
    timezone: str = Form("UTC"),
    attach_image: str = Form("on"),
    dry_run: str = Form("off"),
):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with get_session() as session:
        u = session.get(User, user.id)
        u.post_time, u.timezone = post_time, timezone
        u.attach_image = attach_image == "on"
        u.dry_run = dry_run == "on"
        session.add(u)
        session.commit()
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/dashboard/run-now")
def run_now(request: Request):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    result = run_user_now(user.id)
    return JSONResponse(result)


# ---- billing ----------------------------------------------------------
@app.get("/billing", response_class=HTMLResponse)
def billing(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "billing.html", {"user": user, "settings": settings}
    )


@app.post("/billing/checkout")
def checkout(request: Request):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    if not settings.stripe_secret_key:
        return JSONResponse({"error": "Billing not configured."}, status_code=400)
    import stripe

    stripe.api_key = settings.stripe_secret_key
    session_obj = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        success_url=f"{settings.public_base_url}/dashboard?paid=1",
        cancel_url=f"{settings.public_base_url}/billing",
        client_reference_id=str(user.id),
        metadata={"user_id": str(user.id)},
    )
    return JSONResponse({"url": session_obj.url})


@app.post("/billing/webhook")
async def stripe_webhook(request: Request):
    import stripe

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.stripe_webhook_secret)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=400)

    if event["type"] in ("checkout.session.completed", "customer.subscription.created"):
        obj = event["data"]["object"]
        user_id = (obj.get("metadata") or {}).get("user_id") or obj.get("client_reference_id")
        if user_id:
            with get_session() as session:
                u = session.get(User, int(user_id))
                if u:
                    u.is_active = True
                    u.plan = "pro"
                    session.add(u)
                    session.commit()
    return JSONResponse({"received": True})


# ---- self-host install ------------------------------------------------
@app.get("/install", response_class=HTMLResponse)
def install(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not user.is_active:
        return RedirectResponse("/billing", status_code=303)
    # issue a license key once
    with get_session() as session:
        u = session.get(User, user.id)
        if not u.license_key:
            u.license_key = "rchly_" + secrets.token_urlsafe(24)
            session.add(u)
            session.commit()
        license_key = u.license_key
    return templates.TemplateResponse(
        request, "install.html", {"user": user, "license_key": license_key}
    )
