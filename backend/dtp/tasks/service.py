"""Task service, scheduler, and leased execution with fencing tokens (SRS-021, SRS-022, AT-016, AT-042).
Enforces:
1. Monotonic fencing tokens: stale workers cannot commit results if their lease expired or was taken.
2. Fingerprint deduplication: identical task requests in an investigation return existing task.
3. Dependency satisfaction: ready tasks only queue when all prerequisites have reached acceptable state.
4. Atomic leases: worker acquires lease with heartbeats, releases on finish or failure.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from dtp.db import tenant_tx
from dtp.identity import AuthorizationError, NotFound, Op, Principal, ResourceScope, authorize
from dtp.lifecycle import check_transition
from dtp.repo import Conflict, ValidationFailed, emit_event

DEFAULT_LEASE_SECONDS = 30


class StaleFencingToken(Exception):
    pass


class TaskBlocked(Exception):
    pass


def _calc_fingerprint(capability_id: str, purpose: str, input_refs: list[dict]) -> str:
    raw = json.dumps(
        {"cap": capability_id, "purp": purpose.strip().lower(), "inputs": sorted(input_refs, key=lambda x: str(x))},
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_investigation(
    p: Principal,
    case_id: str,
    snapshot_id: str,
    title: str,
) -> str:
    authorize(p, Op.PROPOSE, ResourceScope(p.tenant_id, case_id))
    inv_id = str(uuid.uuid4())
    with tenant_tx(p.tenant_id) as c:
        # Check case and snapshot
        case = c.execute("SELECT id, origin FROM cases WHERE id=%s", (case_id,)).fetchone()
        if not case:
            raise NotFound("Case not found")
        snap = c.execute("SELECT id FROM world_snapshots WHERE id=%s", (snapshot_id,)).fetchone()
        if not snap:
            raise NotFound("Snapshot not found")

        c.execute(
            "INSERT INTO investigations(id, tenant_id, case_id, snapshot_id, title, state) "
            "VALUES (%s, %s, %s, %s, %s, 'RUNNING')",
            (inv_id, p.tenant_id, case_id, snapshot_id, title),
        )
        emit_event(
            c,
            p,
            case_id=case_id,
            aggregate_id=inv_id,
            revision=1,
            event_type="investigation.created",
            payload_refs=[{"kind": "investigation", "id": inv_id, "revision": 1}],
            origin=case["origin"],
        )
    return inv_id


def submit_task(
    p: Principal,
    case_id: str,
    investigation_id: str,
    capability_id: str,
    purpose: str,
    input_refs: list[dict] | None = None,
    dependency_task_ids: list[str] | None = None,
    priority: int = 50,
    delegation_depth: int = 0,
) -> str:
    """Submit a durable task with fingerprint deduplication and prerequisite dependencies."""
    authorize(p, Op.PROPOSE, ResourceScope(p.tenant_id, case_id))
    input_refs = input_refs or []
    dependency_task_ids = dependency_task_ids or []
    fingerprint = _calc_fingerprint(capability_id, purpose, input_refs)

    with tenant_tx(p.tenant_id) as c:
        # Deduplication check
        existing = c.execute(
            "SELECT id FROM tasks WHERE investigation_id=%s AND fingerprint=%s",
            (investigation_id, fingerprint),
        ).fetchone()
        if existing:
            return str(existing["id"])

        task_id = str(uuid.uuid4())
        initial_state = "WAITING_DEPENDENCY" if dependency_task_ids else "QUEUED"

        c.execute(
            "INSERT INTO tasks("
            "  id, tenant_id, case_id, investigation_id, capability_id, purpose, fingerprint, state,"
            "  priority, delegation_depth, input_refs"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                task_id,
                p.tenant_id,
                case_id,
                investigation_id,
                capability_id,
                purpose,
                fingerprint,
                initial_state,
                priority,
                delegation_depth,
                json.dumps(input_refs),
            ),
        )

        for dep_id in dependency_task_ids:
            c.execute(
                "INSERT INTO task_dependencies(tenant_id, task_id, depends_on_task_id) VALUES (%s, %s, %s)",
                (p.tenant_id, task_id, dep_id),
            )

        emit_event(
            c,
            p,
            case_id=case_id,
            aggregate_id=task_id,
            revision=1,
            event_type="task.admitted",
            payload_refs=[{"kind": "task", "id": task_id, "revision": 1}],
            origin="REAL",
        )

    return task_id


def acquire_task_lease(
    p: Principal,
    worker_id: str,
    capability_allowlist: list[str] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict[str, Any] | None:
    """Atomically claim the highest priority QUEUED task whose dependencies are satisfied.
    Assigns monotonic fencing token.
    """
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(seconds=lease_seconds)

    with tenant_tx(p.tenant_id) as c:
        # Check and resolve any WAITING_DEPENDENCY tasks whose dependencies are satisfied
        c.execute(
            """
            UPDATE tasks t
            SET state = 'QUEUED'
            WHERE t.state = 'WAITING_DEPENDENCY'
              AND NOT EXISTS (
                SELECT 1 FROM task_dependencies d
                JOIN tasks dep ON dep.id = d.depends_on_task_id
                WHERE d.task_id = t.id AND dep.state NOT IN ('SUCCEEDED', 'INCONCLUSIVE')
              )
            """
        )

        # Clean expired leases and reset tasks back to QUEUED for worker recovery
        c.execute(
            """
            WITH expired AS (
              DELETE FROM task_leases
              WHERE lease_expires_at < %s
              RETURNING task_id
            )
            UPDATE tasks
            SET state = 'QUEUED'
            WHERE id IN (SELECT task_id FROM expired) AND state = 'RUNNING'
            """,
            (now,),
        )

        # Select highest-priority ready task
        filter_clause = "AND capability_id = ANY(%s)" if capability_allowlist else ""
        params = [capability_allowlist] if capability_allowlist else []

        task = c.execute(
            f"""
            SELECT id, capability_id, purpose, current_attempt, max_attempts, delegation_depth, input_refs
            FROM tasks
            WHERE state = 'QUEUED' {filter_clause}
            ORDER BY priority DESC, created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """,
            params,
        ).fetchone()

        if not task:
            return None

        task_id = str(task["id"])
        new_attempt = task["current_attempt"] + 1
        attempt_id = str(uuid.uuid4())

        # Fetch prior attempt counter to ensure monotonic fencing token increments
        fencing_token = int(task["current_attempt"]) + 1

        # Upsert lease
        c.execute(
            """
            INSERT INTO task_leases(tenant_id, task_id, attempt_id, worker_id, fencing_token, lease_expires_at, acquired_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, task_id) DO UPDATE SET
              attempt_id = EXCLUDED.attempt_id,
              worker_id = EXCLUDED.worker_id,
              fencing_token = EXCLUDED.fencing_token,
              lease_expires_at = EXCLUDED.lease_expires_at,
              acquired_at = EXCLUDED.acquired_at
            """,
            (p.tenant_id, task_id, attempt_id, worker_id, fencing_token, expiry, now),
        )

        # Update task status to RUNNING
        c.execute(
            "UPDATE tasks SET state='RUNNING', current_attempt=%s WHERE id=%s",
            (new_attempt, task_id),
        )

        return {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "fencing_token": fencing_token,
            "capability_id": task["capability_id"],
            "purpose": task["purpose"],
            "delegation_depth": task["delegation_depth"],
            "input_refs": task["input_refs"] if isinstance(task["input_refs"], list) else json.loads(task["input_refs"]),
            "lease_expires_at": expiry,
        }


def commit_task_result(
    p: Principal,
    task_id: str,
    attempt_id: str,
    fencing_token: bigint,
    status: str,  # SUCCEEDED | INCONCLUSIVE | FAILED
    output_refs: list[dict] | None = None,
    stop_reason: str | None = None,
) -> None:
    """Commit task result only if the fencing token matches the active valid lease (AT-042)."""
    now = datetime.now(timezone.utc)
    output_refs = output_refs or []

    with tenant_tx(p.tenant_id) as c:
        lease = c.execute(
            "SELECT attempt_id, fencing_token, lease_expires_at FROM task_leases WHERE task_id=%s FOR UPDATE",
            (task_id,),
        ).fetchone()

        if not lease or lease["attempt_id"] != uuid.UUID(attempt_id) or lease["fencing_token"] != fencing_token:
            raise StaleFencingToken(f"Stale fencing token {fencing_token} or attempt expired for task {task_id}")

        if lease["lease_expires_at"] < now:
            raise StaleFencingToken("Task lease expired before result commit")

        # Update task terminal state
        c.execute(
            "UPDATE tasks SET state=%s, output_refs=%s, stop_reason=%s, finished_at=clock_timestamp() WHERE id=%s",
            (status, json.dumps(output_refs), stop_reason, task_id),
        )

        # Release lease
        c.execute("DELETE FROM task_leases WHERE task_id=%s", (task_id,))

        # Update dependent tasks waiting for this
        if status in ("SUCCEEDED", "INCONCLUSIVE"):
            c.execute(
                """
                UPDATE tasks t
                SET state = 'QUEUED'
                WHERE t.state = 'WAITING_DEPENDENCY'
                  AND NOT EXISTS (
                    SELECT 1 FROM task_dependencies d
                    JOIN tasks dep ON dep.id = d.depends_on_task_id
                    WHERE d.task_id = t.id AND dep.state NOT IN ('SUCCEEDED', 'INCONCLUSIVE')
                  )
                """
            )

        emit_event(
            c,
            p,
            case_id=None,
            aggregate_id=task_id,
            revision=1,
            event_type="task.completed" if status == "SUCCEEDED" else "task.failed",
            payload_refs=output_refs,
            origin="REAL",
        )
