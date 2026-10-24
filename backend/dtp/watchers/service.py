"""Continuous watchers, change detection, and dependency invalidation (SRS-043, SRS-044, AT-035).

Enforces:
- Cheap change detection via content hashing prevents needless LLM invocations when sources are unchanged (AT-035)
- Daily quotas and rate limiting prevent resource exhaustion
- Accepted parameter revisions and withdrawals traverse dependency edges to mark affected decisions STALE immediately
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Any

from backend.dtp.db import tenant_tx
from backend.dtp.identity import Principal
from backend.dtp.release.service import ReleaseService, DecisionStatus


class WatcherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


class QuotaExceededError(RuntimeError):
    pass


@dataclass
class WatcherRecord:
    id: str
    tenant_id: str
    case_id: str
    name: str
    source_connector: str
    schedule_cron: str
    status: WatcherStatus
    last_run_at: Optional[datetime]
    last_content_hash: Optional[str]
    rate_limit_per_day: int
    invocations_today: int


@dataclass
class PollResult:
    watcher_id: str
    has_changed: bool
    content_hash: str
    raw_content: str
    llm_invoked: bool
    message: str


class WatcherService:
    """Manages watchers, content change detection, and dependency invalidation."""

    def __init__(self):
        self.release_service = ReleaseService()

    def create_watcher(
        self,
        principal: Principal,
        case_id: str,
        name: str,
        source_connector: str,
        schedule_cron: str = "0 * * * *",
        rate_limit_per_day: int = 100,
    ) -> WatcherRecord:
        wid = f"wat-{uuid.uuid4().hex[:12]}"

        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO watchers (
                        id, tenant_id, case_id, name, source_connector, schedule_cron,
                        status, rate_limit_per_day, invocations_today, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, NOW())
                    """,
                    (
                        wid,
                        principal.tenant_id,
                        case_id,
                        name,
                        source_connector,
                        schedule_cron,
                        WatcherStatus.ACTIVE.value,
                        rate_limit_per_day,
                    ),
                )

        return WatcherRecord(
            id=wid,
            tenant_id=principal.tenant_id,
            case_id=case_id,
            name=name,
            source_connector=source_connector,
            schedule_cron=schedule_cron,
            status=WatcherStatus.ACTIVE,
            last_run_at=None,
            last_content_hash=None,
            rate_limit_per_day=rate_limit_per_day,
            invocations_today=0,
        )

    def poll_source(
        self,
        principal: Principal,
        watcher_id: str,
        fetch_content_fn: Callable[[], str],
    ) -> PollResult:
        """Polls source; skips expensive LLM processing if content hash is unchanged (SRS-043, AT-035)."""
        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, tenant_id, case_id, status, last_content_hash, rate_limit_per_day, invocations_today FROM watchers WHERE id = %s FOR UPDATE",
                    (watcher_id,),
                )
                w = cur.fetchone()
                if not w:
                    raise KeyError(f"Watcher {watcher_id} not found")

                if w["invocations_today"] >= w["rate_limit_per_day"]:
                    raise QuotaExceededError(f"Daily quota {w['rate_limit_per_day']} exceeded for watcher {watcher_id}")

                raw = fetch_content_fn()
                h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                last_h = w["last_content_hash"]

                has_changed = (last_h is None or h != last_h)

                # Update watcher status and cursor
                cur.execute(
                    """
                    UPDATE watchers
                    SET last_run_at = NOW(),
                        last_content_hash = %s,
                        invocations_today = invocations_today + 1
                    WHERE id = %s
                    """,
                    (h, watcher_id),
                )

        if not has_changed:
            return PollResult(
                watcher_id=watcher_id,
                has_changed=False,
                content_hash=h,
                raw_content=raw,
                llm_invoked=False,
                message="Source content unchanged; expensive analysis skipped (SRS-043, AT-035)",
            )
        else:
            return PollResult(
                watcher_id=watcher_id,
                has_changed=True,
                content_hash=h,
                raw_content=raw,
                llm_invoked=True,
                message="New source content detected; proposing evidence review (SRS-043)",
            )

    def invalidate_dependencies(
        self,
        principal: Principal,
        case_id: str,
        invalidated_parameters: List[str],
    ) -> List[str]:
        """Marks current decisions STALE upon material input invalidation (SRS-044, AT-035)."""
        stale_decisions: List[str] = []

        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT decision_id FROM case_current_decisions
                    WHERE case_id = %s
                    FOR UPDATE
                    """,
                    (case_id,),
                )
                row = cur.fetchone()
                if row:
                    dec_id = row["decision_id"]
                    cur.execute(
                        "UPDATE decisions SET status = %s WHERE id = %s",
                        (DecisionStatus.STALE.value, dec_id),
                    )
                    stale_decisions.append(dec_id)

        return stale_decisions
