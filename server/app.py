"""Reachly SaaS web app (FastAPI).

Routes:
  /                       landing page
  /login                  Hygaar console login, plus optional legacy Telegram OTP
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
from .hygaar_auth import HygaarAuthError, login_with_hygaar
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
    if settings.telegram_login_enabled:
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


def _is_auto_active_hygaar_user(user_data: dict) -> bool:
    email = (user_data.get("email") or "").strip().lower()
    roles = {str(role).lower() for role in (user_data.get("roles") or [])}
    return settings.free_mode or email in settings.hygaar_pro_emails or "superadmin" in roles


def _upsert_hygaar_user(user_data: dict) -> User:
    hygaar_user_id = str(user_data["user_id"])
    email = (user_data.get("email") or "").strip().lower() or None
    username = user_data.get("username") or email or hygaar_user_id
    roles = ",".join(str(role) for role in (user_data.get("roles") or []))
    with get_session() as session:
        user = session.exec(
            select(User).where(User.hygaar_user_id == hygaar_user_id)
        ).first()
        if not user and email:
            user = session.exec(
                select(User)
                .where(User.email == email)
                .where(User.auth_provider == "hygaar")
            ).first()
        if not user:
            user = User(
                auth_provider="hygaar",
                hygaar_user_id=hygaar_user_id,
                email=email,
                username=username,
                roles=roles,
                is_active=_is_auto_active_hygaar_user(user_data),
                plan="pro" if _is_auto_active_hygaar_user(user_data) else "free",
                dry_run=True,
            )
        else:
            user.auth_provider = "hygaar"
            user.hygaar_user_id = hygaar_user_id
            user.email = email
            user.username = username
            user.roles = roles
            if _is_auto_active_hygaar_user(user_data):
                user.is_active = True
                user.plan = "pro"
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


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
        request,
        "login.html",
        {
            "bot": settings.telegram_bot_username,
            "error": None,
            "telegram_enabled": settings.telegram_login_enabled,
        },
    )


@app.post("/auth/hygaar/login")
def hygaar_login(request: Request, email: str = Form(...), password: str = Form(...)):
    try:
        result = login_with_hygaar(email, password)
    except HygaarAuthError as exc:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "bot": settings.telegram_bot_username,
                "error": str(exc),
                "telegram_enabled": settings.telegram_login_enabled,
                "email": email,
            },
            status_code=401,
        )

    user = _upsert_hygaar_user(result.user)
    request.session["user_id"] = user.id
    request.session["auth_provider"] = "hygaar"
    request.session["hygaar_access_token"] = result.access_token
    request.session["hygaar_refresh_token"] = result.refresh_token
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/auth/send-code")
def send_code(handle: str = Form(...)):
    if not settings.telegram_login_enabled:
        return JSONResponse({"ok": False, "message": "Telegram login is disabled."}, status_code=400)
    ok, msg = generate_and_send_otp(handle)
    return JSONResponse({"ok": ok, "message": msg})


@app.post("/auth/verify")
def verify(request: Request, handle: str = Form(...), code: str = Form(...)):
    if not settings.telegram_login_enabled:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "bot": settings.telegram_bot_username,
                "error": "Telegram login is disabled.",
                "telegram_enabled": False,
            },
            status_code=400,
        )
    ok, user_id = verify_otp(handle, code)
    if not ok:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "bot": settings.telegram_bot_username,
                "error": "Invalid or expired code.",
                "telegram_enabled": settings.telegram_login_enabled,
            },
            status_code=401,
        )
    request.session["user_id"] = user_id
    request.session["auth_provider"] = "telegram"
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


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with get_session() as session:
        profile = session.exec(
            select(BusinessProfileRow).where(BusinessProfileRow.user_id == user.id)
        ).first()
        platform_count = session.exec(
            select(PlatformCredRow).where(PlatformCredRow.user_id == user.id)
        ).all()
        logs = session.exec(
            select(PostLogRow).where(PostLogRow.user_id == user.id)
            .order_by(PostLogRow.id.desc()).limit(5)
        ).all()
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "user": user,
            "profile": profile,
            "platform_count": len([row for row in platform_count if row.mode != "off"]),
            "logs": logs,
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
    brand_logo_path: str = Form(""),
    brand_logo_position: str = Form("bottom-right"),
    text_platform_image_rate: str = Form("0.5"),
    linkedin_image_rate: str = Form(""),
    twitter_image_rate: str = Form(""),
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
            "brand_logo_path": brand_logo_path,
            "brand_logo_position": brand_logo_position,
            "text_platform_image_rate": text_platform_image_rate,
            "linkedin_image_rate": linkedin_image_rate,
            "twitter_image_rate": twitter_image_rate,
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
    consumer_key: str = Form(""),
    consumer_secret: str = Form(""),
    twitter_access_token: str = Form(""),
    twitter_access_token_secret: str = Form(""),
    login_identifier: str = Form(""),
    # linkedin
    access_token: str = Form(""),
    person_urn: str = Form(""),
    organization_id: str = Form(""),
    post_as: str = Form(""),
    company_admin_url: str = Form(""),
    ig_user_id: str = Form(""),
    publish_status: str = Form("draft"),
    expected_account: str = Form(""),
    email: str = Form(""),
    # shared
    username: str = Form(""),
    password: str = Form(""),
):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if platform not in {"twitter", "linkedin", "instagram", "medium"} or mode not in {"off", "api", "browser"}:
        return JSONResponse({"error": "invalid platform settings"}, status_code=400)
    if platform == "medium" and mode == "api":
        return JSONResponse({"error": "Medium API mode is not supported yet. Use browser or off."}, status_code=400)

    secrets_map = {
        k: v for k, v in {
            "oauth2_token": oauth2_token,
            "consumer_key": consumer_key,
            "consumer_secret": consumer_secret,
            "access_token": twitter_access_token if platform == "twitter" else access_token,
            "access_token_secret": twitter_access_token_secret,
            "login_identifier": login_identifier,
            "person_urn": person_urn,
            "organization_id": organization_id,
            "post_as": post_as,
            "company_admin_url": company_admin_url,
            "user_id": ig_user_id,
            "publish_status": publish_status,
            "expected_account": expected_account,
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
    post_times: str = Form("09:00,13:30,21:00"),
    instagram_offset_minutes: int = Form(5),
    medium_times: str = Form("09:30,14:30,19:30"),
    timezone: str = Form("UTC"),
    attach_image: str = Form("on"),
    dry_run: str = Form("off"),
    enable_engagement: str = Form("off"),
    engagement_delay_minutes: int = Form(30),
    engagement_max_comments: int = Form(3),
):
    user = require_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with get_session() as session:
        u = session.get(User, user.id)
        cleaned_post_times = ",".join(_parse_time_list(post_times)) or post_time
        cleaned_medium_times = ",".join(_parse_time_list(medium_times))
        u.post_time = post_time
        u.post_times = cleaned_post_times
        u.instagram_offset_minutes = max(0, min(240, instagram_offset_minutes))
        u.medium_times = cleaned_medium_times
        u.timezone = timezone
        u.attach_image = attach_image == "on"
        u.dry_run = dry_run == "on"
        u.enable_engagement = enable_engagement == "on"
        u.engagement_delay_minutes = max(1, engagement_delay_minutes)
        u.engagement_max_comments = max(1, min(5, engagement_max_comments))
        session.add(u)
        session.commit()
    return RedirectResponse("/dashboard", status_code=303)


def _parse_time_list(value: str) -> list[str]:
    out = []
    for item in (value or "").replace(" ", "").split(","):
        if not item:
            continue
        parts = item.split(":")
        if len(parts) != 2:
            continue
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            out.append(f"{hour:02d}:{minute:02d}")
    return out


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
