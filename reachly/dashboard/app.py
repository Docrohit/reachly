"""Single-tenant Reachly dashboard (Hygaar-first).

Edit goals, posting style, schedule; preview strategy sources; trigger posts.
Protected by REACHLY_DASHBOARD_TOKEN (query ?token= or header X-Reachly-Token).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from reachly.agent import Agent
from reachly.config import AgentConfig
from reachly.context import load_strategy_context
from reachly.settings_store import (
    DEFAULT_POST_TIMES,
    load_dashboard_settings,
    load_goals,
    save_dashboard_settings,
    save_goals,
)

logger = logging.getLogger("reachly.dashboard")
BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

_cfg: AgentConfig | None = None
_app: FastAPI | None = None


def _get_cfg() -> AgentConfig:
    global _cfg
    if _cfg is None:
        env_path = os.environ.get("REACHLY_ENV", "/opt/reachly/.env")
        _cfg = AgentConfig.from_env_file(env_path)
    return _cfg


def _auth_ok(request: Request, cfg: AgentConfig) -> bool:
    token = cfg.dashboard_token
    if not token:
        return True  # dev only — set a token in production
    if request.session.get("reachly_auth"):
        return True
    q = request.query_params.get("token") or request.headers.get("x-reachly-token")
    if q == token:
        request.session["reachly_auth"] = True
        return True
    return False


def create_app() -> FastAPI:
    cfg = _get_cfg()
    app = FastAPI(title="Reachly Dashboard")
    app.add_middleware(SessionMiddleware, secret_key=cfg.dashboard_token or "reachly-dev")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        if not _auth_ok(request, cfg):
            return templates.TemplateResponse(
                request, "auth.html", {"error": None}, status_code=401
            )
        dash = load_dashboard_settings(cfg.data_dir)
        goals = load_goals(cfg.data_dir)
        strategy = load_strategy_context(
            data_dir=cfg.data_dir,
            context_repo=dash.get("context_repo") or cfg.context_repo,
            agents_path=cfg.agents_md_path,
            product_theory_path=cfg.product_theory_path,
            posting_style=dash.get("posting_style", "thought_leader"),
        )
        logs = _recent_logs(cfg.data_dir)
        return templates.TemplateResponse(
            request,
            "hygaar.html",
            {
                "cfg": cfg,
                "dash": dash,
                "goals": goals,
                "strategy_source": strategy.source,
                "strategy_preview": strategy.for_prompt()[:2500],
                "logs": logs,
                "default_times": ", ".join(DEFAULT_POST_TIMES),
            },
        )

    @app.post("/auth")
    def auth(request: Request, token: str = Form(...)):
        if token == (cfg.dashboard_token or ""):
            request.session["reachly_auth"] = True
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            request, "auth.html", {"error": "Invalid token."}, status_code=401
        )

    @app.post("/save")
    def save(
        request: Request,
        goals: str = Form(""),
        posting_style: str = Form("thought_leader"),
        post_times: str = Form("09:00,13:30,21:00"),
        instagram_offset_minutes: int = Form(5),
        context_repo: str = Form(""),
    ):
        if not _auth_ok(request, cfg):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        times = [t.strip() for t in post_times.replace(" ", "").split(",") if t.strip()]
        save_goals(cfg.data_dir, goals)
        save_dashboard_settings(
            cfg.data_dir,
            post_times=times,
            posting_style=posting_style,
            context_repo=context_repo.strip(),
            instagram_offset_minutes=instagram_offset_minutes,
        )
        return RedirectResponse("/?saved=1", status_code=303)

    @app.post("/run-now")
    def run_now(request: Request, theme: str = Form("")):
        if not _auth_ok(request, cfg):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        def _job():
            try:
                agent = Agent.from_config(cfg)
                agent.run_once(theme=theme or None)
                agent.close()
            except Exception:  # noqa: BLE001
                logger.exception("Dashboard run-now failed")

        threading.Thread(target=_job, daemon=True).start()
        return JSONResponse({"ok": True, "message": "Post job started. Refresh in ~60s for logs."})

    return app


def _recent_logs(data_dir: Path, limit: int = 15) -> list[dict]:
    db = data_dir / "history.db"
    if not db.is_file():
        return []
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT created_at, platform, ok, permalink, error, hook FROM posts "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = _get_cfg()
    app = create_app()
    port = cfg.dashboard_port
    logger.info("Reachly dashboard on http://0.0.0.0:%s (set REACHLY_DASHBOARD_TOKEN)", port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
