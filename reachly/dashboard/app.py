"""Single-tenant Reachly dashboard (Hygaar-first).

Edit goals, posting style, schedule; preview strategy sources; trigger posts.
Protected by REACHLY_DASHBOARD_TOKEN (query ?token= or header X-Reachly-Token).
"""
from __future__ import annotations

import io
import logging
import os
import re
import sqlite3
import threading
import zipfile
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from reachly.agent import Agent
from reachly.config import AgentConfig
from reachly.context import load_strategy_context
from reachly.longform_video import LongFormManualBrief
from reachly.settings_store import (
    DEFAULT_POST_TIMES,
    load_dashboard_settings,
    load_goals,
    save_dashboard_settings,
    save_goals,
)
from reachly.storage import History

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
                request,
                "auth.html",
                {"error": None, "base_path": _base_path(request)},
                status_code=401,
            )
        asset_hours = _asset_hours(request.query_params.get("assets"))
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
        assets = _recent_assets(cfg, hours=asset_hours)
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
                "assets": assets,
                "asset_hours": asset_hours,
                "base_path": _base_path(request),
                "default_times": ", ".join(DEFAULT_POST_TIMES),
            },
        )

    @app.post("/auth")
    def auth(request: Request, token: str = Form(...)):
        if token == (cfg.dashboard_token or ""):
            request.session["reachly_auth"] = True
            return RedirectResponse(_dashboard_url(request, "/"), status_code=303)
        return templates.TemplateResponse(
            request,
            "auth.html",
            {"error": "Invalid token.", "base_path": _base_path(request)},
            status_code=401,
        )

    @app.post("/save")
    def save(
        request: Request,
        goals: str = Form(""),
        posting_style: str = Form("thought_leader"),
        post_times: str = Form("09:00,12:00,15:00,18:00,21:00"),
        instagram_offset_minutes: int = Form(5),
        longform_video_times: str = Form("11:30,17:30"),
        context_repo: str = Form(""),
    ):
        if not _auth_ok(request, cfg):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        times = [t.strip() for t in post_times.replace(" ", "").split(",") if t.strip()]
        video_times = [
            t.strip()
            for t in longform_video_times.replace(" ", "").split(",")
            if t.strip()
        ]
        save_goals(cfg.data_dir, goals)
        save_dashboard_settings(
            cfg.data_dir,
            post_times=times,
            posting_style=posting_style,
            context_repo=context_repo.strip(),
            instagram_offset_minutes=instagram_offset_minutes,
            longform_video_times=video_times,
        )
        return RedirectResponse(_dashboard_url(request, "/?saved=1"), status_code=303)

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

    @app.post("/run-longform-video")
    def run_longform_video(
        request: Request,
        topic: str = Form(""),
        title: str = Form(""),
        hook: str = Form(""),
        payoff: str = Form(""),
    ):
        if not _auth_ok(request, cfg):
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        def _job():
            try:
                agent = Agent.from_config(cfg)
                agent.run_longform_video_slot(
                    theme=topic.strip() or None,
                    manual=LongFormManualBrief(
                        topic=topic.strip() or None,
                        title=title.strip() or None,
                        hook=hook.strip() or None,
                        payoff=payoff.strip() or None,
                    ),
                )
                agent.close()
            except Exception:  # noqa: BLE001
                logger.exception("Dashboard long-form video run failed")

        threading.Thread(target=_job, daemon=True).start()
        return JSONResponse({"ok": True, "message": "Long-form video job started. Refresh later for assets/logs."})

    @app.get("/assets/{post_id}/media")
    def asset_media(
        request: Request,
        post_id: int,
        download: bool = Query(False),
    ):
        if not _auth_ok(request, cfg):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        row = _asset_row_by_id(cfg.data_dir, post_id)
        if not row:
            raise HTTPException(status_code=404, detail="Asset not found")
        path = _resolve_media_path(cfg, row.get("media_local_path") or "")
        if not path:
            raise HTTPException(status_code=404, detail="Asset file is no longer available")
        filename = _download_filename(row, path)
        disposition = "attachment" if download else "inline"
        return FileResponse(
            str(path),
            media_type=_media_type(path, row.get("media_kind")),
            filename=filename,
            content_disposition_type=disposition,
        )

    @app.get("/assets/archive")
    def asset_archive(request: Request, hours: int = Query(24)):
        if not _auth_ok(request, cfg):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        asset_hours = _asset_hours(str(hours))
        assets = _recent_assets(cfg, hours=asset_hours, limit=300)
        buffer = io.BytesIO()
        count = 0
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for asset in assets:
                path = asset.get("resolved_path")
                if path and Path(path).is_file():
                    media_name = _download_filename(asset, Path(path))
                    zf.write(path, f"media/{media_name}")
                    count += 1
                text = (asset.get("copy_text") or "").strip()
                if text:
                    zf.writestr(f"text/post_{asset['id']}.txt", text)
        if count == 0:
            raise HTTPException(status_code=404, detail="No downloadable assets in this window")
        buffer.seek(0)
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="reachly_assets_last_{asset_hours}h.zip"'
                )
            },
        )

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


def _base_path(request: Request) -> str:
    raw = request.headers.get("x-forwarded-prefix", "")
    if not raw:
        return ""
    cleaned = "/" + raw.strip().strip("/")
    return "" if cleaned == "/" else cleaned


def _dashboard_url(request: Request, path: str) -> str:
    prefix = _base_path(request)
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{prefix}{suffix}" if prefix else suffix


def _asset_hours(value: str | None) -> int:
    try:
        hours = int(value or "24")
    except ValueError:
        return 24
    return 48 if hours == 48 else 24


def _recent_assets(cfg: AgentConfig, *, hours: int = 24, limit: int = 150) -> list[dict]:
    history = History(cfg.data_dir)
    try:
        rows = history.recent_media_assets(hours=hours, limit=limit)
    finally:
        history.close()

    grouped: dict[str, dict] = {}
    for row in rows:
        key = row.get("media_local_path") or row.get("media_public_url") or str(row["id"])
        asset = grouped.setdefault(
            key,
            {
                **row,
                "copy_text": _copy_text(row),
                "platforms": [],
                "_platform_summary": {},
                "resolved_path": None,
                "file_exists": False,
                "file_size": "",
                "created_display": _display_time(row.get("created_at")),
            },
        )
        _add_platform_summary(asset, row)
        if row.get("ok") and not asset.get("ok"):
            asset.update({k: row.get(k) for k in row.keys()})
            asset["copy_text"] = _copy_text(row)
        path = _resolve_media_path(cfg, row.get("media_local_path") or "")
        if path and not asset["file_exists"]:
            asset["resolved_path"] = str(path)
            asset["file_exists"] = True
            asset["file_size"] = _file_size(path)
    assets = list(grouped.values())
    for asset in assets:
        summaries = asset.pop("_platform_summary", {})
        asset["platforms"] = [_platform_label(summary) for summary in summaries.values()]
    return assets


def _add_platform_summary(asset: dict, row: dict) -> None:
    platform = row.get("platform") or "unknown"
    summaries = asset.setdefault("_platform_summary", {})
    summary = summaries.setdefault(
        platform,
        {
            "platform": platform,
            "ok_count": 0,
            "fail_count": 0,
            "error": "",
        },
    )
    if row.get("ok"):
        summary["ok_count"] += 1
    else:
        summary["fail_count"] += 1
        summary["error"] = row.get("error") or summary["error"]


def _platform_label(summary: dict) -> dict:
    platform = summary["platform"]
    ok_count = int(summary.get("ok_count") or 0)
    fail_count = int(summary.get("fail_count") or 0)
    ok = ok_count > 0
    if ok and fail_count:
        label = f"{platform} ok ({fail_count} retry fail{'s' if fail_count != 1 else ''})"
    elif ok:
        label = f"{platform} ok"
    else:
        label = f"{platform} fail"
        if fail_count > 1:
            label = f"{label} x{fail_count}"
    return {
        "platform": platform,
        "ok": ok,
        "label": label,
        "error": summary.get("error"),
    }


def _asset_row_by_id(data_dir: Path, post_id: int) -> dict | None:
    history = History(data_dir)
    history.close()
    db = data_dir / "history.db"
    if not db.is_file():
        return None
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT id, created_at, theme, hook, body, platform, ok, permalink, error,
               impressions, likes, comments, shares, analytics_note,
               media_kind, media_local_path, media_public_url, media_prompt, post_text
        FROM posts
        WHERE id = ? AND media_kind IN ('image', 'video')
        """,
        (post_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _resolve_media_path(cfg: AgentConfig, raw_path: str) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    candidates = [path] if path.is_absolute() else [
        Path.cwd() / path,
        cfg.data_dir.parent / path,
        cfg.data_dir / path,
        cfg.data_dir / "media" / path.name,
    ]
    roots = [cfg.data_dir.resolve()]
    if cfg.public_media_dir:
        roots.append(Path(cfg.public_media_dir).expanduser().resolve())
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        if any(resolved == root or root in resolved.parents for root in roots):
            return resolved
    return None


def _copy_text(row: dict) -> str:
    stored = (row.get("post_text") or "").strip()
    if stored:
        return stored
    parts = [(row.get("hook") or "").strip(), "", (row.get("body") or "").strip()]
    return "\n".join(part for part in parts if part is not None).strip()


def _display_time(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return value


def _file_size(path: Path) -> str:
    size = path.stat().st_size
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def _download_filename(row: dict, path: Path) -> str:
    created = (row.get("created_at") or "").replace(":", "").replace("-", "")[:15]
    theme = _safe_name(row.get("theme") or "reachly")
    platform = _safe_name(row.get("platform") or "asset")
    stem = "_".join(part for part in [created, platform, theme, str(row.get("id"))] if part)
    return f"{stem}{path.suffix.lower() or '.bin'}"


def _safe_name(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return text[:48] or "asset"


def _media_type(path: Path, kind: str | None) -> str:
    suffix = path.suffix.lower()
    if kind == "video" or suffix in {".mp4", ".mov", ".webm"}:
        return "video/mp4"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = _get_cfg()
    app = create_app()
    port = cfg.dashboard_port
    logger.info("Reachly dashboard on http://0.0.0.0:%s (set REACHLY_DASHBOARD_TOKEN)", port)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
