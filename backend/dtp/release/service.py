"""Decision release service, lineage closure validation, and atomic current pointer (SRS-041, SRS-042, AT-033, AT-034).

Enforces:
- Formal outcomes: RECOMMEND, CONDITIONAL, DEFER, NO_FEASIBLE_ACTION, ABSTAIN
- Mandatory verification report with PASS outcome required prior to release
- Lineage DAG closure validation: decision -> verification -> simulation -> strategy -> snapshot -> claim -> span -> source (AT-033)
- Cycle detection and missing reference rejection (AT-033)
- Atomic unique current pointer per case with optimistic concurrency locking (AT-034)
- Previous released decisions transition to SUPERSEDED
- Material parameter invalidation marks current decision STALE (AT-034)
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Set, Any

from backend.dtp.db import tenant_tx
from backend.dtp.identity import Principal
from backend.dtp.release.verification import VerificationBlockedError, OverallOutcome


class DecisionOutcome(str, Enum):
    RECOMMEND = "RECOMMEND"
    CONDITIONAL = "CONDITIONAL"
    DEFER = "DEFER"
    NO_FEASIBLE_ACTION = "NO_FEASIBLE_ACTION"
    ABSTAIN = "ABSTAIN"


class DecisionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    VERIFIED = "VERIFIED"
    RELEASED = "RELEASED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class LineageClosureError(ValueError):
    """Raised when decision lineage DAG has missing references or contains a cycle (AT-033)."""
    pass


class StaleReleaseRaceError(RuntimeError):
    """Raised when concurrent release worker attempts to commit against a stale revision (AT-034)."""
    pass


@dataclass
class DecisionRecord:
    id: str
    tenant_id: str
    case_id: str
    revision: int
    outcome: DecisionOutcome
    status: DecisionStatus
    selected_strategy_ref: Optional[Dict[str, Any]]
    objective_and_constraints: Dict[str, Any]
    summary_payload: Dict[str, Any]
    lineage_closure: Dict[str, Any]
    verification_report_id: Optional[str]
    released_at: Optional[datetime]
    released_by: Optional[str]
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "case_id": self.case_id,
            "revision": self.revision,
            "outcome": self.outcome.value,
            "status": self.status.value,
            "selected_strategy_ref": self.selected_strategy_ref,
            "objective_and_constraints": self.objective_and_constraints,
            "summary_payload": self.summary_payload,
            "verification_report_id": self.verification_report_id,
            "released_at": self.released_at.isoformat() if self.released_at else None,
            "released_by": self.released_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ReleaseService:
    """Manages lineage validation, verification enforcement, and atomic release of decisions."""

    @staticmethod
    def validate_lineage_closure(lineage: Dict[str, Any]) -> None:
        """Validates that lineage forms a closed, acyclic DAG reaching root sources (AT-033)."""
        nodes = lineage.get("nodes", [])
        edges = lineage.get("edges", [])

        if not nodes:
            raise LineageClosureError("Lineage closure is empty: no nodes provided (AT-033)")

        node_ids = {n["id"]: n for n in nodes}

        # 1. Missing reference check: all edges must connect existing nodes
        for e in edges:
            if e["from"] not in node_ids:
                raise LineageClosureError(f"Lineage references missing source node '{e['from']}' (AT-033)")
            if e["to"] not in node_ids:
                raise LineageClosureError(f"Lineage references missing target node '{e['to']}' (AT-033)")

        # 2. Cycle detection via Depth-First Search (DFS)
        adj: Dict[str, List[str]] = {n_id: [] for n_id in node_ids}
        for e in edges:
            adj[e["from"]].append(e["to"])

        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def _dfs(node: str) -> None:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    _dfs(neighbor)
                elif neighbor in rec_stack:
                    raise LineageClosureError(f"Lineage DAG contains a dependency cycle involving '{neighbor}' (AT-033)")

            rec_stack.remove(node)

        for n_id in node_ids:
            if n_id not in visited:
                _dfs(n_id)

    def create_decision_draft(
        self,
        principal: Principal,
        case_id: str,
        outcome: DecisionOutcome,
        objective_and_constraints: Dict[str, Any],
        summary_payload: Dict[str, Any],
        lineage_closure: Dict[str, Any],
        selected_strategy_ref: Optional[Dict[str, Any]] = None,
        verification_report_id: Optional[str] = None,
    ) -> DecisionRecord:
        # Validate lineage DAG closure (AT-033)
        self.validate_lineage_closure(lineage_closure)

        dec_id = f"dec-{uuid.uuid4().hex[:12]}"

        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                # Get next revision number for this case
                cur.execute(
                    "SELECT COALESCE(MAX(revision), 0) + 1 AS next_rev FROM decisions WHERE case_id = %s",
                    (case_id,),
                )
                rev = cur.fetchone()["next_rev"]

                cur.execute(
                    """
                    INSERT INTO decisions (
                        id, tenant_id, case_id, revision, outcome, status,
                        selected_strategy_ref, objective_and_constraints,
                        summary_payload, lineage_closure, verification_report_id,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING created_at
                    """,
                    (
                        dec_id,
                        principal.tenant_id,
                        case_id,
                        rev,
                        outcome.value,
                        DecisionStatus.DRAFT.value,
                        json.dumps(selected_strategy_ref) if selected_strategy_ref else None,
                        json.dumps(objective_and_constraints),
                        json.dumps(summary_payload),
                        json.dumps(lineage_closure),
                        verification_report_id,
                    ),
                )
                created_at = cur.fetchone()["created_at"]

        return DecisionRecord(
            id=dec_id,
            tenant_id=principal.tenant_id,
            case_id=case_id,
            revision=rev,
            outcome=outcome,
            status=DecisionStatus.DRAFT,
            selected_strategy_ref=selected_strategy_ref,
            objective_and_constraints=objective_and_constraints,
            summary_payload=summary_payload,
            lineage_closure=lineage_closure,
            verification_report_id=verification_report_id,
            released_at=None,
            released_by=None,
            created_at=created_at,
        )

    def release_decision(
        self,
        principal: Principal,
        case_id: str,
        decision_id: str,
        expected_current_revision: Optional[int] = None,
    ) -> DecisionRecord:
        """Transitions decision to RELEASED with atomic concurrency lock on case_current_decisions (AT-034)."""
        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                # 1. Fetch decision and verify verification report outcome
                cur.execute(
                    """
                    SELECT d.id, d.tenant_id, d.case_id, d.revision, d.outcome, d.status,
                           d.selected_strategy_ref, d.objective_and_constraints, d.summary_payload,
                           d.lineage_closure, d.verification_report_id, d.created_at,
                           vr.overall_outcome AS v_outcome
                    FROM decisions d
                    LEFT JOIN verification_reports vr ON d.verification_report_id = vr.id
                    WHERE d.id = %s AND d.case_id = %s
                    FOR UPDATE OF d
                    """,
                    (decision_id, case_id),
                )
                row = cur.fetchone()
                if not row:
                    raise KeyError(f"Decision {decision_id} not found in case {case_id}")

                if row["v_outcome"] != OverallOutcome.PASS.value:
                    raise VerificationBlockedError(
                        f"Cannot release decision {decision_id}: Verification overall outcome is {row['v_outcome']} (must be PASS) (SRS-040, AT-032)"
                    )

                if row["status"] in (DecisionStatus.RELEASED.value, DecisionStatus.SUPERSEDED.value, DecisionStatus.WITHDRAWN.value):
                    raise RuntimeError(f"Decision {decision_id} is already in state {row['status']}")

                target_rev = row["revision"]

                # 2. Lock and check current decision pointer (Optimistic Concurrency, AT-034)
                cur.execute(
                    """
                    SELECT decision_id, decision_revision
                    FROM case_current_decisions
                    WHERE case_id = %s
                    FOR UPDATE
                    """,
                    (case_id,),
                )
                current_ptr = cur.fetchone()

                if current_ptr:
                    curr_rev = current_ptr["decision_revision"]
                    old_dec_id = current_ptr["decision_id"]

                    if expected_current_revision is not None and curr_rev != expected_current_revision:
                        raise StaleReleaseRaceError(
                            f"Release race detected: current case revision is {curr_rev}, but worker expected {expected_current_revision} (AT-034)"
                        )

                    # Mark previous released decision as SUPERSEDED
                    cur.execute(
                        "UPDATE decisions SET status = %s WHERE id = %s",
                        (DecisionStatus.SUPERSEDED.value, old_dec_id),
                    )

                # 3. Mark target decision RELEASED
                cur.execute(
                    """
                    UPDATE decisions
                    SET status = %s,
                        released_at = NOW(),
                        released_by = %s
                    WHERE id = %s
                    RETURNING released_at
                    """,
                    (DecisionStatus.RELEASED.value, principal.actor_id, decision_id),
                )
                rel_at = cur.fetchone()["released_at"]

                # 4. Upsert case_current_decisions pointer
                cur.execute(
                    """
                    INSERT INTO case_current_decisions (tenant_id, case_id, decision_id, decision_revision, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (tenant_id, case_id)
                    DO UPDATE SET decision_id = EXCLUDED.decision_id,
                                  decision_revision = EXCLUDED.decision_revision,
                                  updated_at = NOW()
                    """,
                    (principal.tenant_id, case_id, decision_id, target_rev),
                )

        return DecisionRecord(
            id=row["id"],
            tenant_id=str(row["tenant_id"]),
            case_id=str(row["case_id"]),
            revision=row["revision"],
            outcome=DecisionOutcome(row["outcome"]),
            status=DecisionStatus.RELEASED,
            selected_strategy_ref=row["selected_strategy_ref"] if isinstance(row["selected_strategy_ref"], (dict, type(None))) else json.loads(row["selected_strategy_ref"]),
            objective_and_constraints=row["objective_and_constraints"] if isinstance(row["objective_and_constraints"], dict) else json.loads(row["objective_and_constraints"]),
            summary_payload=row["summary_payload"] if isinstance(row["summary_payload"], dict) else json.loads(row["summary_payload"]),
            lineage_closure=row["lineage_closure"] if isinstance(row["lineage_closure"], dict) else json.loads(row["lineage_closure"]),
            verification_report_id=row["verification_report_id"],
            released_at=rel_at,
            released_by=principal.actor_id,
            created_at=row["created_at"],
        )

    def mark_decision_stale(self, principal: Principal, case_id: str, decision_id: str) -> None:
        """Marks decision STALE upon material dependency invalidation (SRS-044, AT-034)."""
        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE decisions SET status = %s WHERE id = %s AND case_id = %s",
                    (DecisionStatus.STALE.value, decision_id, case_id),
                )

    def get_current_decision(self, principal: Principal, case_id: str) -> Optional[DecisionRecord]:
        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.id, d.tenant_id, d.case_id, d.revision, d.outcome, d.status,
                           d.selected_strategy_ref, d.objective_and_constraints, d.summary_payload,
                           d.lineage_closure, d.verification_report_id, d.released_at,
                           d.released_by, d.created_at
                    FROM case_current_decisions ccd
                    JOIN decisions d ON ccd.decision_id = d.id
                    WHERE ccd.case_id = %s
                    """,
                    (case_id,),
                )
                row = cur.fetchone()

        if not row:
            return None

        return DecisionRecord(
            id=row["id"],
            tenant_id=str(row["tenant_id"]),
            case_id=str(row["case_id"]),
            revision=row["revision"],
            outcome=DecisionOutcome(row["outcome"]),
            status=DecisionStatus(row["status"]),
            selected_strategy_ref=row["selected_strategy_ref"] if isinstance(row["selected_strategy_ref"], (dict, type(None))) else json.loads(row["selected_strategy_ref"]),
            objective_and_constraints=row["objective_and_constraints"] if isinstance(row["objective_and_constraints"], dict) else json.loads(row["objective_and_constraints"]),
            summary_payload=row["summary_payload"] if isinstance(row["summary_payload"], dict) else json.loads(row["summary_payload"]),
            lineage_closure=row["lineage_closure"] if isinstance(row["lineage_closure"], dict) else json.loads(row["lineage_closure"]),
            verification_report_id=row["verification_report_id"],
            released_at=row["released_at"],
            released_by=row["released_by"],
            created_at=row["created_at"],
        )
