"""Durable generation ledger. Single-host SQLite, atomic claims, private assets."""
import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from contextlib import contextmanager, closing


class LeaseLost(RuntimeError):
    pass


def root():
    path = Path(os.getenv("REACHLY_GENERATION_DATA", ".reachly_generation")).resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


@contextmanager
def database():
    with closing(sqlite3.connect(root() / "jobs.sqlite3", timeout=20)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT, business TEXT, request_key TEXT, digest TEXT, payload TEXT, provider TEXT, state TEXT, result TEXT, updated REAL, UNIQUE(owner,business,request_key))")
        db.execute("CREATE TABLE IF NOT EXISTS generation_organisations (owner TEXT NOT NULL, organisation TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(owner,organisation))")
        db.execute("CREATE TABLE IF NOT EXISTS generation_clinics (owner TEXT NOT NULL, business TEXT NOT NULL, organisation TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(owner,business))")
        yield db


def submit(owner, request_key, payload, provider, max_hourly_jobs=20):
    request_key = str(uuid.UUID(request_key))
    encoded = json.dumps(payload, sort_keys=True)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        organisation = payload.get("organisation_id")
        if organisation:
            if not db.execute("SELECT 1 FROM generation_organisations WHERE owner=? AND organisation=?", (owner, organisation)).fetchone():
                raise PermissionError("Organisation is not registered")
            binding = db.execute("SELECT organisation FROM generation_clinics WHERE owner=? AND business=?", (owner, payload["business_id"])).fetchone()
            if binding and binding["organisation"] != organisation:
                raise PermissionError("Clinic belongs to another organisation")
        old = db.execute("SELECT * FROM jobs WHERE owner=? AND business=? AND request_key=?", (owner, payload["business_id"], request_key)).fetchone()
        if old:
            if old["digest"] != digest:
                raise ValueError("Idempotency key already used with different inputs")
            return dict(old)
        count = db.execute("SELECT COUNT(*) FROM jobs WHERE owner=? AND business=? AND updated>?", (owner, payload["business_id"], time.time()-3600)).fetchone()[0]
        if count >= max_hourly_jobs:
            raise OverflowError("Business generation hourly limit reached")
        if organisation:
            db.execute("INSERT OR IGNORE INTO generation_clinics VALUES (?,?,?,?)", (owner, payload["business_id"], organisation, time.time()))
        job_id = str(uuid.uuid4())
        db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)", (job_id, owner, payload["business_id"], request_key, digest, encoded, provider, "queued", json.dumps({"candidates": [], "warnings": [], "stage": "queued"}), time.time()))
        return dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def register_organisation(owner, organisation):
    with database() as db:
        db.execute("INSERT OR IGNORE INTO generation_organisations VALUES (?,?,?)", (owner, organisation, time.time()))


def organisation_registered(owner, organisation):
    with database() as db:
        return db.execute("SELECT 1 FROM generation_organisations WHERE owner=? AND organisation=?", (owner, organisation)).fetchone() is not None


def get(job_id, owner):
    with database() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=? AND owner=?", (str(uuid.UUID(job_id)), owner)).fetchone()
        return dict(row) if row else None


def claim():
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        # A lost worker may have incurred provider charges; do not blindly replay it.
        db.execute("UPDATE jobs SET state='needs_attention' WHERE state='running' AND updated<?", (time.time()-1800,))
        row = db.execute("SELECT * FROM jobs WHERE state='queued' AND provider!='personal-workspace' ORDER BY updated LIMIT 1").fetchone()
        if not row:
            return None
        db.execute("UPDATE jobs SET state='running',updated=? WHERE id=?", (time.time(), row["id"]))
        return dict(row)


def save(job_id, result, state="running"):
    with database() as db:
        updated = db.execute("UPDATE jobs SET result=?,state=?,updated=? WHERE id=? AND state='running'", (json.dumps(result), state, time.time(), job_id))
        if not updated.rowcount:
            raise LeaseLost("Generation lease ended; no more provider calls may start")


def response(row):
    return {"job_id": row["id"], "business_id": row["business"], "state": row["state"], **json.loads(row["result"])}


def recent_hooks(owner, business):
    with database() as db:
        rows = db.execute("SELECT result FROM jobs WHERE owner=? AND business=? AND state IN ('completed','partial') ORDER BY updated DESC LIMIT 8", (owner, business)).fetchall()
    return [c["post"]["hook"] for row in rows for c in json.loads(row["result"]).get("candidates", []) if c.get("state") == "completed"][:40]
