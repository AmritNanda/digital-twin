"""Lifecycle transition guards (SRS Annex D1). Unlisted transitions are rejected."""
from __future__ import annotations

_T = {
    "case": {"OPEN": {"PAUSED", "CLOSED"}, "PAUSED": {"OPEN", "CLOSED"}, "CLOSED": {"ARCHIVED"}},
    "investigation": {
        "CREATED": {"RUNNING", "CANCELLED"},
        "RUNNING": {"WAITING_FOR_INPUT", "COMPLETED", "STOPPED", "FAILED", "CANCELLED"},
        "WAITING_FOR_INPUT": {"RUNNING", "STOPPED", "FAILED", "CANCELLED"},
    },
    "task_admission": {"PROPOSED": {"QUEUED", "WAITING_DEPENDENCY", "WAITING_INPUT", "CANCELLED", "EXPIRED"}},
    "task_dispatch": {
        "QUEUED": {"RUNNING", "CANCELLED", "EXPIRED"},
        "WAITING_DEPENDENCY": {"QUEUED", "CANCELLED", "EXPIRED"},
        "WAITING_INPUT": {"QUEUED", "CANCELLED", "EXPIRED"},
    },
    "task_attempt": {
        "RUNNING": {"SUCCEEDED", "INCONCLUSIVE", "FAILED", "CANCELLED", "EXPIRED", "RETRY_PENDING",
                    "WAITING_DEPENDENCY", "WAITING_INPUT"},
        "RETRY_PENDING": {"QUEUED", "FAILED", "CANCELLED", "EXPIRED"},
    },
    "instance": {
        "REQUESTED": {"ADMITTED", "CANCELLED", "EXPIRED"},
        "ADMITTED": {"RUNNING", "CANCELLED", "EXPIRED"},
        "RUNNING": {"WAITING", "SUCCEEDED", "INCONCLUSIVE", "FAILED", "CANCELLED", "EXPIRED"},
        "WAITING": {"RUNNING", "FAILED", "CANCELLED", "EXPIRED"},
    },
    "review": {"PROPOSED": {"NEEDS_REVIEW", "ACCEPTED", "REJECTED"},
               "NEEDS_REVIEW": {"ACCEPTED", "REJECTED"}, "ACCEPTED": {"WITHDRAWN"}},
    "hypothesis": {"PROPOSED": {"TESTING", "UNRESOLVED"},
                   "TESTING": {"SUPPORTED_IN_SCOPE", "REFUTED_IN_SCOPE", "UNRESOLVED"}},
    "challenge": {"OPEN": {"TESTING", "REJECTED", "SUPERSEDED"},
                  "TESTING": {"RESOLVED", "UNRESOLVED", "REJECTED", "SUPERSEDED"}},
    "decision": {"DRAFT": {"IN_REVIEW", "WITHDRAWN"}, "IN_REVIEW": {"VERIFIED", "WITHDRAWN"},
                 "VERIFIED": {"RELEASED", "WITHDRAWN"},
                 "RELEASED": {"STALE", "SUPERSEDED", "WITHDRAWN"}, "STALE": {"SUPERSEDED", "WITHDRAWN"}},
    "experiment": {"DRAFT": {"IN_REVIEW", "ABORTED"}, "IN_REVIEW": {"APPROVED", "ABORTED"},
                   "APPROVED": {"RUNNING", "ABORTED"}, "RUNNING": {"PAUSED", "COMPLETED", "ABORTED"},
                   "PAUSED": {"RUNNING", "ABORTED"}, "COMPLETED": {"ANALYZED"}},
    "action": {"DRAFT": {"PENDING_APPROVAL", "REVOKED"},
               "PENDING_APPROVAL": {"APPROVED", "REVOKED", "EXPIRED"},
               "APPROVED": {"DISPATCHING", "REVOKED", "EXPIRED"},
               "DISPATCHING": {"SUCCEEDED", "FAILED", "UNKNOWN"},
               "UNKNOWN": {"SUCCEEDED", "FAILED"}},
    "approval": {"APPROVED": {"REVOKED", "EXPIRED"}},
}

TERMINAL_TASK_STATES = frozenset({"SUCCEEDED", "INCONCLUSIVE", "FAILED", "CANCELLED", "EXPIRED"})


class IllegalTransition(Exception):
    pass


def object_kinds() -> list[str]:
    return sorted(_T)


def allowed(obj: str, frm: str) -> frozenset[str]:
    return frozenset(_T[obj].get(frm, ()))


def check_transition(obj: str, frm: str, to: str, *, reconciled: bool = False) -> None:
    """Raise IllegalTransition unless listed. Action UNKNOWN->final requires reconciliation."""
    if obj not in _T:
        raise IllegalTransition(f"unknown lifecycle object {obj!r}")
    if to not in _T[obj].get(frm, ()):
        raise IllegalTransition(f"{obj}: {frm} -> {to} is not permitted")
    if obj == "action" and frm == "UNKNOWN" and not reconciled:
        raise IllegalTransition("action UNKNOWN may only change after reconciliation")
