"""External action gateway with cryptographic approval hashes and timeout reconciliation (SRS-047, AT-042, AT-047).

Enforces:
- Cryptographic SHA-256 payload approval hash verification
- Tamper detection: modified payloads fail execution
- Idempotency: duplicate requests return existing execution receipt
- Timeout handling: in-flight timeouts transition to UNKNOWN and require reconciliation before retry
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
from backend.dtp.identity import Op, Principal, ResourceScope, authorize


class ActionStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHING = "DISPATCHING"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    RECONCILED = "RECONCILED"


class ApprovalHashMismatchError(ValueError):
    """Raised when execution payload does not match approved cryptographic hash (AT-047)."""
    pass


class ActionAlreadyExecutedError(RuntimeError):
    pass


@dataclass
class ActionReceipt:
    id: str
    tenant_id: str
    case_id: str
    action_type: str
    payload: Dict[str, Any]
    approval_hash: str
    idempotency_key: str
    status: ActionStatus
    execution_receipt: Optional[Dict[str, Any]]
    created_at: datetime
    executed_at: Optional[datetime]


class ActionGateway:
    """Secure external action gateway (A22 / External Gateway)."""

    @staticmethod
    def compute_approval_hash(payload: Dict[str, Any]) -> str:
        """Deterministic canonical JSON SHA-256 hash."""
        canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    def request_action_approval(
        self,
        principal: Principal,
        case_id: str,
        action_type: str,
        payload: Dict[str, Any],
        idempotency_key: str,
    ) -> ActionReceipt:
        authorize(principal, Op.PROPOSE, ResourceScope(principal.tenant_id, case_id))
        h = self.compute_approval_hash(payload)
        rec_id = f"act-{uuid.uuid4().hex[:12]}"

        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                # Check idempotency
                cur.execute(
                    "SELECT id, tenant_id, case_id, action_type, payload, approval_hash, idempotency_key, status, execution_receipt, created_at, executed_at FROM action_receipts WHERE idempotency_key = %s",
                    (idempotency_key,),
                )
                existing = cur.fetchone()
                if existing:
                    if (existing["approval_hash"] != h or str(existing["case_id"]) != str(case_id)
                            or existing["action_type"] != action_type):
                        raise ApprovalHashMismatchError("Idempotency key already belongs to a different action")
                    return ActionReceipt(
                        id=existing["id"],
                        tenant_id=str(existing["tenant_id"]),
                        case_id=str(existing["case_id"]),
                        action_type=existing["action_type"],
                        payload=existing["payload"] if isinstance(existing["payload"], dict) else json.loads(existing["payload"]),
                        approval_hash=existing["approval_hash"],
                        idempotency_key=existing["idempotency_key"],
                        status=ActionStatus(existing["status"]),
                        execution_receipt=existing["execution_receipt"],
                        created_at=existing["created_at"],
                        executed_at=existing["executed_at"],
                    )

                cur.execute(
                    """
                    INSERT INTO action_receipts (
                        id, tenant_id, case_id, action_type, payload, approval_hash,
                        idempotency_key, status, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING created_at
                    """,
                    (
                        rec_id,
                        principal.tenant_id,
                        case_id,
                        action_type,
                        json.dumps(payload),
                        h,
                        idempotency_key,
                        ActionStatus.PENDING.value,
                    ),
                )
                created_at = cur.fetchone()["created_at"]

        return ActionReceipt(
            id=rec_id,
            tenant_id=principal.tenant_id,
            case_id=case_id,
            action_type=action_type,
            payload=payload,
            approval_hash=h,
            idempotency_key=idempotency_key,
            status=ActionStatus.PENDING,
            execution_receipt=None,
            created_at=created_at,
            executed_at=None,
        )

    def execute_action(
        self,
        principal: Principal,
        action_id: str,
        execution_payload: Dict[str, Any],
        external_executor: Callable[[Dict[str, Any]], Tuple[str, Dict[str, Any]]],
    ) -> ActionReceipt:
        """Executes external action with cryptographic verification and timeout handling (AT-047)."""
        # 1. Fetch action record
        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, tenant_id, case_id, action_type, payload, approval_hash, idempotency_key, status, execution_receipt, created_at, executed_at FROM action_receipts WHERE id = %s FOR UPDATE",
                    (action_id,),
                )
                rec = cur.fetchone()
                if not rec:
                    raise KeyError(f"Action {action_id} not found")

                authorize(principal, Op.APPROVE_ACTION,
                          ResourceScope(principal.tenant_id, str(rec["case_id"]), rec["action_type"]))

                if rec["status"] == ActionStatus.EXECUTED.value:
                    # Idempotent return
                    return ActionReceipt(
                        id=rec["id"],
                        tenant_id=str(rec["tenant_id"]),
                        case_id=str(rec["case_id"]),
                        action_type=rec["action_type"],
                        payload=rec["payload"] if isinstance(rec["payload"], dict) else json.loads(rec["payload"]),
                        approval_hash=rec["approval_hash"],
                        idempotency_key=rec["idempotency_key"],
                        status=ActionStatus.EXECUTED,
                        execution_receipt=rec["execution_receipt"],
                        created_at=rec["created_at"],
                        executed_at=rec["executed_at"],
                    )

                if rec["status"] != ActionStatus.PENDING.value:
                    raise ActionAlreadyExecutedError(f"Action {action_id} is {rec['status']}; reconcile before retrying")

                # 2. Cryptographic approval verification: tamper detection (AT-047)
                exec_hash = self.compute_approval_hash(execution_payload)
                if exec_hash != rec["approval_hash"]:
                    raise ApprovalHashMismatchError(
                        f"Execution payload hash {exec_hash} does not match approved hash {rec['approval_hash']}. Payload was modified (SRS-047, AT-047)!"
                    )

                cur.execute("UPDATE action_receipts SET status = %s WHERE id = %s",
                            (ActionStatus.DISPATCHING.value, action_id))

        # 3. Call external sandbox executor
        try:
            status_code, receipt = external_executor(execution_payload)
            final_status = ActionStatus.EXECUTED if status_code == "SUCCESS" else ActionStatus.FAILED
        except TimeoutError:
            # Reconcile timeout to UNKNOWN (AT-042)
            final_status = ActionStatus.UNKNOWN
            receipt = {"error": "External call timed out; transitioning to UNKNOWN pending reconciliation (AT-042)"}
        except Exception as exc:
            final_status = ActionStatus.UNKNOWN
            receipt = {"error": f"External call outcome unknown ({type(exc).__name__}); reconcile before retrying"}

        # 4. Update status in database
        with tenant_tx(principal.tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE action_receipts
                    SET status = %s,
                        execution_receipt = %s,
                        executed_at = NOW()
                    WHERE id = %s AND status = %s
                    RETURNING executed_at
                    """,
                    (final_status.value, json.dumps(receipt), action_id, ActionStatus.DISPATCHING.value),
                )
                updated = cur.fetchone()
                if not updated:
                    raise ActionAlreadyExecutedError(f"Action {action_id} changed during dispatch")
                exec_at = updated["executed_at"]

        return ActionReceipt(
            id=action_id,
            tenant_id=principal.tenant_id,
            case_id=str(rec["case_id"]),
            action_type=rec["action_type"],
            payload=execution_payload,
            approval_hash=rec["approval_hash"],
            idempotency_key=rec["idempotency_key"],
            status=final_status,
            execution_receipt=receipt,
            created_at=rec["created_at"],
            executed_at=exec_at,
        )
