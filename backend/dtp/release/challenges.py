"""Adversarial falsification, challenge lifecycle, and dispute resolution (SRS-038, AT-030).

Implements:
- Concrete failure propositions with testable alternatives and reversal criteria
- Formal lifecycle: OPEN -> TESTING -> RESOLVED | UNRESOLVED | REJECTED | SUPERSEDED
- Refutation test execution and input revision invalidation
- Unresolved material challenges cannot be dismissed by restating rationale and block release
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional, Any, Tuple

from backend.dtp.db import tenant_tx
from backend.dtp.identity import Principal


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MATERIAL = "MATERIAL"
    MINOR = "MINOR"


class ChallengeStatus(str, Enum):
    OPEN = "OPEN"
    TESTING = "TESTING"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class UnresolvedMaterialChallengeError(RuntimeError):
    """Raised when release is attempted with open or unresolved material challenges."""
    pass


@dataclass
class ChallengeRecord:
    id: str
    tenant_id: str
    case_id: str
    decision_proposal_id: Optional[str]
    challenger_agent_id: str
    title: str
    severity: Severity
    status: ChallengeStatus
    affected_artifact_refs: List[Dict[str, Any]]
    failure_proposition: str
    proposed_test: str
    reversal_criteria: str
    test_result: Optional[str] = None
    resolution_notes: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "case_id": self.case_id,
            "decision_proposal_id": self.decision_proposal_id,
            "challenger_agent_id": self.challenger_agent_id,
            "title": self.title,
            "severity": self.severity.value,
            "status": self.status.value,
            "affected_artifact_refs": self.affected_artifact_refs,
            "failure_proposition": self.failure_proposition,
            "proposed_test": self.proposed_test,
            "reversal_criteria": self.reversal_criteria,
            "test_result": self.test_result,
            "resolution_notes": self.resolution_notes,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


class ChallengeService:
    """Manages creation, testing, and dispute resolution for adversarial challenges."""

    def create_challenge(
        self,
        principal: Principal,
        case_id: str,
        title: str,
        severity: Severity,
        failure_proposition: str,
        proposed_test: str,
        reversal_criteria: str,
        affected_artifact_refs: List[Dict[str, Any]],
        decision_proposal_id: Optional[str] = None,
        challenger_agent_id: str = "A17_DEVILS_ADVOCATE",
    ) -> ChallengeRecord:
        if not title or not failure_proposition or not proposed_test or not reversal_criteria:
            raise ValueError("All challenge fields (title, failure_proposition, proposed_test, reversal_criteria) are mandatory")

        cid = f"chal-{uuid.uuid4().hex[:12]}"

        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO challenges (
                        id, tenant_id, case_id, decision_proposal_id, challenger_agent_id,
                        title, severity, status, affected_artifact_refs, failure_proposition,
                        proposed_test, reversal_criteria, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (
                        cid,
                        principal.tenant_id,
                        case_id,
                        decision_proposal_id,
                        challenger_agent_id,
                        title,
                        severity.value,
                        ChallengeStatus.OPEN.value,
                        json.dumps(affected_artifact_refs),
                        failure_proposition,
                        proposed_test,
                        reversal_criteria,
                    ),
                )

        return ChallengeRecord(
            id=cid,
            tenant_id=principal.tenant_id,
            case_id=case_id,
            decision_proposal_id=decision_proposal_id,
            challenger_agent_id=challenger_agent_id,
            title=title,
            severity=severity,
            status=ChallengeStatus.OPEN,
            affected_artifact_refs=affected_artifact_refs,
            failure_proposition=failure_proposition,
            proposed_test=proposed_test,
            reversal_criteria=reversal_criteria,
        )

    def execute_test(
        self,
        principal: Principal,
        challenge_id: str,
        test_runner: Callable[[], Tuple[bool, str]],
    ) -> ChallengeRecord:
        """Runs the proposed refutation test.
        
        test_runner returns:
            (refutation_confirmed, result_summary)
            If refutation_confirmed is True: challenge is confirmed (status = RESOLVED with refutation)
            If False: refutation failed (status = RESOLVED with rejected refutation)
        """
        # Transition to TESTING first
        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE challenges SET status = %s WHERE id = %s",
                    (ChallengeStatus.TESTING.value, challenge_id),
                )

        refuted, result_text = test_runner()

        # Update resolution
        final_status = ChallengeStatus.RESOLVED if refuted else ChallengeStatus.REJECTED

        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE challenges
                    SET status = %s,
                        test_result = %s,
                        resolution_notes = %s,
                        resolved_by = %s,
                        resolved_at = NOW()
                    WHERE id = %s
                    RETURNING tenant_id, case_id, decision_proposal_id, challenger_agent_id,
                              title, severity, affected_artifact_refs, failure_proposition,
                              proposed_test, reversal_criteria, resolved_at
                    """,
                    (
                        final_status.value,
                        result_text,
                        f"Refutation test completed. Refutation confirmed: {refuted}",
                        principal.actor_id,
                        challenge_id,
                    ),
                )
                row = cur.fetchone()

        return ChallengeRecord(
            id=challenge_id,
            tenant_id=str(row["tenant_id"]),
            case_id=str(row["case_id"]),
            decision_proposal_id=row["decision_proposal_id"],
            challenger_agent_id=row["challenger_agent_id"],
            title=row["title"],
            severity=Severity(row["severity"]),
            status=final_status,
            affected_artifact_refs=row["affected_artifact_refs"] if isinstance(row["affected_artifact_refs"], list) else json.loads(row["affected_artifact_refs"]),
            failure_proposition=row["failure_proposition"],
            proposed_test=row["proposed_test"],
            reversal_criteria=row["reversal_criteria"],
            test_result=result_text,
            resolution_notes=f"Refutation test completed. Refutation confirmed: {refuted}",
            resolved_by=principal.actor_id,
            resolved_at=row["resolved_at"],
        )

    def list_unresolved_material_challenges(self, principal: Principal, case_id: str) -> List[ChallengeRecord]:
        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, tenant_id, case_id, decision_proposal_id, challenger_agent_id,
                           title, severity, status, affected_artifact_refs, failure_proposition,
                           proposed_test, reversal_criteria, test_result, resolution_notes,
                           resolved_by, resolved_at
                    FROM challenges
                    WHERE case_id = %s
                      AND severity IN ('CRITICAL', 'MATERIAL')
                      AND status IN ('OPEN', 'TESTING', 'UNRESOLVED')
                    ORDER BY created_at ASC
                    """,
                    (case_id,),
                )
                rows = cur.fetchall()

        res = []
        for r in rows:
            refs = r["affected_artifact_refs"]
            if isinstance(refs, str):
                refs = json.loads(refs)
            res.append(ChallengeRecord(
                id=r["id"],
                tenant_id=str(r["tenant_id"]),
                case_id=str(r["case_id"]),
                decision_proposal_id=r["decision_proposal_id"],
                challenger_agent_id=r["challenger_agent_id"],
                title=r["title"],
                severity=Severity(r["severity"]),
                status=ChallengeStatus(r["status"]),
                affected_artifact_refs=refs,
                failure_proposition=r["failure_proposition"],
                proposed_test=r["proposed_test"],
                reversal_criteria=r["reversal_criteria"],
                test_result=r["test_result"],
                resolution_notes=r["resolution_notes"],
                resolved_by=r["resolved_by"],
                resolved_at=r["resolved_at"],
            ))
        return res
