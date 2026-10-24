"""Durable, owner-scoped records for the document-led workspace."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

from pwdlib import PasswordHash

from config import ROOT_DIR

PASSWORDS = PasswordHash.recommended()
DB_PATH = Path(os.getenv("STRATEGY_DB_PATH", str(ROOT_DIR / "data" / "workspace.sqlite3")))


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def initialize():
    with database() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, question TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft', source_snapshot TEXT NOT NULL DEFAULT '{}',
                approval TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(owner_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, case_id TEXT NOT NULL, filename TEXT NOT NULL,
                size INTEGER NOT NULL, path TEXT NOT NULL, chunks INTEGER NOT NULL,
                preview TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(case_id) REFERENCES cases(id)
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, case_id TEXT NOT NULL, version INTEGER NOT NULL,
                status TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}', twin TEXT NOT NULL DEFAULT '{}',
                assumptions TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
                FOREIGN KEY(case_id) REFERENCES cases(id), UNIQUE(case_id, version)
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, run_id TEXT,
                created_at TEXT NOT NULL, payload TEXT NOT NULL,
                FOREIGN KEY(case_id) REFERENCES cases(id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, run_id TEXT,
                role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(case_id) REFERENCES cases(id)
            );
            CREATE INDEX IF NOT EXISTS events_case_id ON events(case_id,id);
            CREATE INDEX IF NOT EXISTS documents_case_id ON documents(case_id);
            CREATE INDEX IF NOT EXISTS runs_case_id ON runs(case_id,version);
        """)
    email = os.getenv("STRATEGY_DEMO_EMAIL", "").strip().lower()
    password = os.getenv("STRATEGY_DEMO_PASSWORD", "")
    if email and password:
        create_user(email, password)


def create_user(email: str, password: str) -> str:
    with database() as db:
        row = db.execute("SELECT id FROM users WHERE email=?", (email.lower(),)).fetchone()
        if row:
            return row["id"]
        user_id = str(uuid4())
        db.execute("INSERT INTO users VALUES (?,?,?)", (user_id, email.lower(), PASSWORDS.hash(password)))
        return user_id


def verify_user(email: str, password: str) -> dict | None:
    with database() as db:
        row = db.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()
    if row and PASSWORDS.verify(password, row["password_hash"]):
        return {"id": row["id"], "email": row["email"]}
    return None


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    with database() as db:
        db.execute("INSERT INTO sessions VALUES (?,?,?)", (token, user_id, expires))
    return token


def session_user(token: str | None) -> dict | None:
    if not token:
        return None
    with database() as db:
        row = db.execute("""SELECT users.id,users.email FROM sessions JOIN users
            ON users.id=sessions.user_id WHERE sessions.token=? AND sessions.expires_at>?""",
            (token, timestamp())).fetchone()
    return dict(row) if row else None


def revoke_session(token: str | None):
    if token:
        with database() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (token,))


def create_case(owner_id: str) -> dict:
    now, case_id = timestamp(), str(uuid4())
    with database() as db:
        db.execute("INSERT INTO cases(id,owner_id,created_at,updated_at) VALUES (?,?,?,?)",
                   (case_id, owner_id, now, now))
    return get_case(case_id, owner_id)


def get_case(case_id: str, owner_id: str) -> dict | None:
    with database() as db:
        row = db.execute("SELECT * FROM cases WHERE id=? AND owner_id=?", (case_id, owner_id)).fetchone()
    if not row:
        return None
    case = dict(row)
    case["source_snapshot"] = json.loads(case["source_snapshot"])
    case["approval"] = json.loads(case["approval"])
    case["documents"] = list_documents(case_id)
    case["runs"] = list_runs(case_id)
    case["messages"] = list_messages(case_id)
    case["events"] = list_events(case_id)
    return case


def update_case(case_id: str, **fields):
    allowed = {"question", "status", "source_snapshot", "approval"}
    updates = {key: (json.dumps(value, default=str) if key in {"source_snapshot", "approval"} else value)
               for key, value in fields.items() if key in allowed}
    if not updates:
        return
    updates["updated_at"] = timestamp()
    assignments = ",".join(f"{key}=?" for key in updates)
    with database() as db:
        db.execute(f"UPDATE cases SET {assignments} WHERE id=?", (*updates.values(), case_id))


def add_document(case_id: str, filename: str, size: int, path: Path, chunks: int, preview: str) -> dict:
    doc_id = str(uuid4())
    now = timestamp()
    with database() as db:
        db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
                   (doc_id, case_id, filename, size, str(path), chunks, preview, now))
    return {"id": doc_id, "filename": filename, "size": size, "chunks": chunks,
            "preview": preview, "created_at": now}


def list_documents(case_id: str) -> list[dict]:
    with database() as db:
        rows = db.execute("SELECT id,filename,size,chunks,preview,created_at FROM documents WHERE case_id=? ORDER BY created_at", (case_id,)).fetchall()
    return [dict(row) for row in rows]


def list_document_paths(case_id: str) -> list[dict]:
    """Internal source names for mapping retrieved spans to owned documents."""
    with database() as db:
        rows = db.execute("SELECT id,path FROM documents WHERE case_id=?", (case_id,)).fetchall()
    return [dict(row) for row in rows]


def remove_document(case_id: str, doc_id: str) -> Path | None:
    with database() as db:
        row = db.execute("SELECT path FROM documents WHERE case_id=? AND id=?", (case_id, doc_id)).fetchone()
        if row:
            db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    return Path(row["path"]) if row else None


def append_event(case_id: str, payload: dict, run_id: str | None = None) -> dict:
    created = timestamp()
    with database() as db:
        cursor = db.execute("INSERT INTO events(case_id,run_id,created_at,payload) VALUES (?,?,?,?)",
                            (case_id, run_id, created, json.dumps(payload, default=str)))
        event_id = cursor.lastrowid
    return {"id": event_id, "case_id": case_id, "run_id": run_id, "created_at": created, **payload}


def list_events(case_id: str, after: int = 0) -> list[dict]:
    with database() as db:
        rows = db.execute("SELECT * FROM events WHERE case_id=? AND id>? ORDER BY id", (case_id, after)).fetchall()
    return [{"id": row["id"], "case_id": case_id, "run_id": row["run_id"],
             "created_at": row["created_at"], **json.loads(row["payload"])} for row in rows]


def add_run(case_id: str, status: str, result: dict | None = None,
            twin: dict | None = None, assumptions: dict | None = None) -> dict:
    with database() as db:
        version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM runs WHERE case_id=?", (case_id,)).fetchone()[0]
        run_id, now = str(uuid4()), timestamp()
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)",
                   (run_id, case_id, version, status, json.dumps(result or {}, default=str),
                    json.dumps(twin or {}, default=str), json.dumps(assumptions or {}, default=str), now))
    return get_run(run_id)


def get_run(run_id: str) -> dict | None:
    with database() as db:
        row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return None
    run = dict(row)
    for key in ("result", "twin", "assumptions"):
        run[key] = json.loads(run[key])
    return run


def latest_run(case_id: str) -> dict | None:
    with database() as db:
        row = db.execute("SELECT id FROM runs WHERE case_id=? ORDER BY version DESC LIMIT 1", (case_id,)).fetchone()
    return get_run(row["id"]) if row else None


def latest_completed_run(case_id: str) -> dict | None:
    with database() as db:
        row = db.execute("SELECT id FROM runs WHERE case_id=? AND status='completed' ORDER BY version DESC LIMIT 1", (case_id,)).fetchone()
    return get_run(row["id"]) if row else None


def list_runs(case_id: str) -> list[dict]:
    with database() as db:
        rows = db.execute("SELECT id FROM runs WHERE case_id=? ORDER BY version", (case_id,)).fetchall()
    return [get_run(row["id"]) for row in rows]


def update_run(run_id: str, **fields):
    allowed = {"status", "result", "twin", "assumptions"}
    updates = {key: (json.dumps(value, default=str) if key != "status" else value)
               for key, value in fields.items() if key in allowed}
    if updates:
        with database() as db:
            db.execute("UPDATE runs SET " + ",".join(f"{key}=?" for key in updates) + " WHERE id=?",
                       (*updates.values(), run_id))


def add_message(case_id: str, run_id: str | None, role: str, content: str) -> dict:
    created = timestamp()
    with database() as db:
        cursor = db.execute("INSERT INTO messages(case_id,run_id,role,content,created_at) VALUES (?,?,?,?,?)",
                            (case_id, run_id, role, content, created))
        return {"id": cursor.lastrowid, "run_id": run_id, "role": role, "content": content, "created_at": created}


def list_messages(case_id: str) -> list[dict]:
    with database() as db:
        rows = db.execute("SELECT id,run_id,role,content,created_at FROM messages WHERE case_id=? ORDER BY id", (case_id,)).fetchall()
    return [dict(row) for row in rows]
