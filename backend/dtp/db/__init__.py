"""Database access: owner connection (migrations only) and tenant-bound app connections.

The app role `twin_app` is non-owner/non-superuser; RLS (FORCE) is keyed on `app.tenant_id`, set
with `set_config(..., true)` (transaction-local) from the server-derived Principal only.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

MIGRATIONS = Path(__file__).parent / "migrations"
_ROOT = Path(__file__).resolve().parents[3]


def _env(name: str, default: str | None = None) -> str | None:
    if name in os.environ:
        return os.environ[name]
    envf = _ROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return default


class DbUnconfigured(RuntimeError):
    """Capability UNCONFIGURED; message names variables only, never values."""


def _dsn(user: str, pw_var: str) -> str:
    pw = _env(pw_var)
    if not pw:
        raise DbUnconfigured(f"{pw_var} is not set")
    return (f"host={_env('POSTGRES_HOST', '127.0.0.1')} port={_env('POSTGRES_PORT', '5433')} "
            f"dbname={_env('POSTGRES_DB', 'twin')} user={user} password={pw} connect_timeout=5")


def owner_conn() -> psycopg.Connection:
    return psycopg.connect(_dsn("twin_owner", "POSTGRES_OWNER_PASSWORD"), autocommit=True, row_factory=dict_row)


def app_conn() -> psycopg.Connection:
    return psycopg.connect(_dsn("twin_app", "POSTGRES_APP_PASSWORD"), row_factory=dict_row)


def migrate() -> list[str]:
    """Create app role (idempotent), apply pending migrations in order. Returns applied versions."""
    applied: list[str] = []
    with owner_conn() as c:
        app_pw = _env("POSTGRES_APP_PASSWORD")
        if not app_pw:
            raise DbUnconfigured("POSTGRES_APP_PASSWORD is not set")
        exists = c.execute("SELECT 1 FROM pg_roles WHERE rolname='twin_app'").fetchone()
        stmt = "ALTER ROLE twin_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}" if exists \
            else "CREATE ROLE twin_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
        c.execute(sql.SQL(stmt).format(sql.Literal(app_pw)))
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                  "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        done = {r["version"] for r in c.execute("SELECT version FROM schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.stem in done:
                continue
            with c.transaction():
                c.execute(f.read_text(encoding="utf-8"))
                c.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (f.stem,))
            applied.append(f.stem)
        c.execute("GRANT USAGE ON SCHEMA public TO twin_app")
    return applied


@contextmanager
def tenant_tx(tenant_id: str | UUID):
    """Transaction bound to one tenant. Commit on success, rollback on error."""
    UUID(str(tenant_id))  # reject non-UUID input early
    conn = app_conn()
    try:
        with conn.transaction():
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
            yield conn
    finally:
        conn.close()
