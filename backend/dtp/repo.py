"""Canonical repository services (SRS-004/015/016/020/024). All writes: authorize -> validate ->
single transaction (state + event + outbox + audit). Tenant/actor derive from Principal only.
Not yet covered: evidence-span reference closure (needs intake stage), stale propagation.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Callable

import psycopg

from . import semantic
from .contracts import validate_artifact
from .db import owner_conn, tenant_tx
from .identity import (AuthorizationError, NotFound, Op, Principal, ResourceScope, authorize,
                       require_independent_review)
from .jurisdiction import resolve_context
from .lifecycle import check_transition


class Conflict(Exception):
    pass


class ValidationFailed(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _u() -> str:
    return str(uuid.uuid4())


def _canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), default=str)


# ---------------- bootstrap (owner connection; not an API surface) ----------------
def bootstrap_tenant(name: str, owner_email: str) -> tuple[str, str]:
    tid, uid = _u(), _u()
    with owner_conn() as c:
        with c.transaction():
            c.execute("SELECT set_config('app.tenant_id', %s, true)", (tid,))
            c.execute("INSERT INTO tenants(id,name) VALUES (%s,%s)", (tid, name))
            c.execute("INSERT INTO users(id,tenant_id,email) VALUES (%s,%s,%s)", (uid, tid, owner_email))
            c.execute("INSERT INTO memberships(tenant_id,user_id,role) VALUES (%s,%s,'owner')", (tid, uid))
    return tid, uid


def add_user(tenant_id: str, email: str, roles: list[str]) -> str:
    uid = _u()
    with owner_conn() as c:
        with c.transaction():
            c.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
            c.execute("INSERT INTO users(id,tenant_id,email) VALUES (%s,%s,%s)", (uid, tenant_id, email))
            for r in roles:
                c.execute("INSERT INTO memberships(tenant_id,user_id,role) VALUES (%s,%s,%s)",
                          (tenant_id, uid, r))
    return uid


# ---------------- events / outbox ----------------
def emit_event(conn, p: Principal, *, case_id: str | None, aggregate_id: str, revision: int,
               event_type: str, payload_refs: list, origin: str, correlation_id: str | None = None,
               causation_id: str | None = None, occurred_at: datetime | None = None) -> str:
    eid = _u()
    conn.execute(
        "INSERT INTO events(event_id,tenant_id,case_id,aggregate_id,aggregate_revision,event_type,"
        "occurred_at,correlation_id,causation_id,actor_id,payload_refs,origin) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (eid, p.tenant_id, case_id, aggregate_id, revision, event_type, occurred_at,
         correlation_id or _u(), causation_id, p.actor_id, json.dumps(payload_refs), origin))
    conn.execute("INSERT INTO outbox(event_id,tenant_id) VALUES (%s,%s)", (eid, p.tenant_id))
    return eid


def audit(conn, p: Principal, action: str, subject: str | None, detail: dict | None = None) -> None:
    conn.execute("INSERT INTO audit_records(tenant_id,actor_id,action,subject,detail) VALUES (%s,%s,%s,%s,%s)",
                 (p.tenant_id, p.actor_id, action, subject, json.dumps(detail or {})))


def publish_pending(p: Principal, consumer: str, handler: Callable[[dict], None], limit: int = 100,
                    crash_before_ack: bool = False) -> int:
    """At-least-once delivery. Handler runs once per (consumer, event) thanks to receipts; outbox row is
    marked published only after the handler succeeds. `crash_before_ack` exists for acceptance tests."""
    done = 0
    with tenant_tx(p.tenant_id) as c:
        rows = c.execute(
            "SELECT e.* FROM outbox o JOIN events e USING (event_id) WHERE o.published_at IS NULL "
            "ORDER BY e.seq LIMIT %s FOR UPDATE OF o SKIP LOCKED", (limit,)).fetchall()
        for ev in rows:
            fresh = c.execute(
                "INSERT INTO consumer_receipts(tenant_id,consumer,event_id) VALUES (%s,%s,%s) "
                "ON CONFLICT DO NOTHING RETURNING 1", (p.tenant_id, consumer, ev["event_id"])).fetchone()
            if fresh:
                handler(ev)
            if crash_before_ack:
                raise RuntimeError("simulated crash before ack")
            c.execute("UPDATE outbox SET published_at=clock_timestamp(), attempts=attempts+1 WHERE event_id=%s",
                      (ev["event_id"],))
            done += 1
    return done


# ---------------- cases ----------------
def create_case(p: Principal, *, title: str, objective: str | None, horizon_days: int | None,
                country: str | None = None, currency: str | None = None, tax_basis: str | None = None,
                origin: str = "REAL") -> str:
    authorize(p, Op.REVISE_OBJECTIVES, ResourceScope(p.tenant_id))
    ctx = resolve_context(country, currency, tax_basis)
    cid = _u()
    with tenant_tx(p.tenant_id) as c:
        c.execute("INSERT INTO cases(id,tenant_id,title,objective,horizon_days,country,currency,tax_basis,"
                  "defaulted_fields,origin,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                  (cid, p.tenant_id, title, objective, horizon_days, ctx["country"], ctx["currency"],
                   ctx["tax_basis"], ctx["defaulted_fields"], origin, p.actor_id))
        emit_event(c, p, case_id=cid, aggregate_id=cid, revision=1, event_type="case.created",
                   payload_refs=[{"kind": "entity", "id": cid, "revision": 1}], origin=origin)
        audit(c, p, "case.create", cid)
    return cid


def get_case(p: Principal, case_id: str) -> dict:
    authorize(p, Op.READ, ResourceScope(p.tenant_id, case_id))
    with tenant_tx(p.tenant_id) as c:
        r = c.execute("SELECT * FROM cases WHERE id=%s", (case_id,)).fetchone()
    if not r:
        raise NotFound("case not found")  # same response for absent and other-tenant
    return r


def transition_case(p: Principal, case_id: str, to: str) -> None:
    authorize(p, Op.REVISE_OBJECTIVES, ResourceScope(p.tenant_id, case_id))
    with tenant_tx(p.tenant_id) as c:
        r = c.execute("SELECT state, revision, origin FROM cases WHERE id=%s FOR UPDATE", (case_id,)).fetchone()
        if not r:
            raise NotFound("case not found")
        check_transition("case", r["state"], to)
        c.execute("UPDATE cases SET state=%s, revision=revision+1 WHERE id=%s", (to, case_id))
        emit_event(c, p, case_id=case_id, aggregate_id=case_id, revision=r["revision"] + 1,
                   event_type=f"case.{to.lower()}", payload_refs=[], origin=r["origin"])
        audit(c, p, "case.transition", case_id, {"from": r["state"], "to": to})


# ---------------- claims ----------------
def _claim_from_artifact(a: dict) -> dict:
    v = a.get("scope", {})
    return {"predicate": a["predicate"], "proposition": a["proposition"], "value": a.get("value"),
            "epistemic_state": a["epistemic_state"], "valid_from": v.get("valid_from"),
            "valid_to": v.get("valid_to"), "origin": a["origin"], "material": a["material"],
            "evidence_refs": a.get("evidence_refs", [])}


def propose_claim(p: Principal, case_id: str, artifact: dict, *, claim_id: str | None = None,
                  idempotency_key: str | None = None) -> tuple[str, int]:
    """Create revision 1 (or next revision when claim_id given). Server tenant wins; mismatch is rejected."""
    authorize(p, Op.PROPOSE, ResourceScope(p.tenant_id, case_id))
    validate_artifact(artifact)
    errs = []
    if artifact["artifact_type"] != "ClaimProposal":
        errs.append("artifact_type must be ClaimProposal")
    if artifact["tenant_id"] != p.tenant_id:
        errs.append("payload tenant_id does not match authenticated tenant")
    if artifact["review_state"] != "PROPOSED":
        errs.append("proposals must arrive as PROPOSED; lifecycle is server-controlled")
    errs += semantic.check_claim(artifact)
    if errs:
        raise ValidationFailed(errs)
    row = _claim_from_artifact(artifact)
    req_hash = hashlib.sha256(_canon([case_id, claim_id, row]).encode()).hexdigest()
    with tenant_tx(p.tenant_id) as c:
        if idempotency_key:
            prev = c.execute("SELECT request_hash, response FROM idempotency_keys WHERE actor_id=%s AND key=%s",
                             (p.actor_id, idempotency_key)).fetchone()
            if prev:
                if prev["request_hash"] != req_hash:
                    raise Conflict("idempotency key reused with a different request")
                return prev["response"]["claim_id"], prev["response"]["revision"]
        case = c.execute("SELECT origin, state FROM cases WHERE id=%s", (case_id,)).fetchone()
        if not case:
            raise NotFound("case not found")
        if case["state"] != "OPEN":
            raise Conflict(f"case is {case['state']}; new proposals rejected")
        if row["origin"] == "REAL" and case["origin"] == "FIXTURE":
            raise ValidationFailed(["REAL claim cannot enter a FIXTURE case"])
        if claim_id:
            last = c.execute("SELECT revision FROM claim_revisions WHERE claim_id=%s "
                             "ORDER BY revision DESC LIMIT 1 FOR UPDATE", (claim_id,)).fetchone()
            if last is None:
                raise NotFound("claim not found")
            rev = last["revision"] + 1
        else:
            claim_id, rev = _u(), 1
        c.execute("INSERT INTO claim_revisions(tenant_id,claim_id,revision,case_id,predicate,proposition,value,"
                  "epistemic_state,valid_from,valid_to,origin,material,evidence_refs,actor_id) "
                  "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                  (p.tenant_id, claim_id, rev, case_id, row["predicate"], row["proposition"],
                   json.dumps(row["value"]) if row["value"] is not None else None, row["epistemic_state"],
                   row["valid_from"], row["valid_to"], row["origin"], row["material"],
                   json.dumps(row["evidence_refs"]), p.actor_id))
        emit_event(c, p, case_id=case_id, aggregate_id=claim_id, revision=rev, event_type="claim.proposed",
                   payload_refs=[{"kind": "claim", "id": claim_id, "revision": rev}], origin=row["origin"])
        audit(c, p, "claim.propose", claim_id, {"revision": rev})
        if idempotency_key:
            c.execute("INSERT INTO idempotency_keys(tenant_id,actor_id,key,request_hash,response) "
                      "VALUES (%s,%s,%s,%s,%s)", (p.tenant_id, p.actor_id, idempotency_key, req_hash,
                                                  json.dumps({"claim_id": claim_id, "revision": rev})))
    return claim_id, rev


def review_claim(p: Principal, claim_id: str, revision: int, decision: str, *, category: str,
                 self_review_allowed: bool = False) -> dict:
    """decision: ACCEPTED | REJECTED | NEEDS_REVIEW | WITHDRAWN. Accept needs category authority."""
    if decision not in ("ACCEPTED", "REJECTED", "NEEDS_REVIEW", "WITHDRAWN"):
        raise ValidationFailed([f"unknown decision {decision}"])
    with tenant_tx(p.tenant_id) as c:
        r = c.execute("SELECT case_id, review_state, actor_id, origin FROM claim_revisions "
                      "WHERE claim_id=%s AND revision=%s FOR UPDATE", (claim_id, revision)).fetchone()
        if not r:
            raise NotFound("claim not found")
        case_id = str(r["case_id"])
        authorize(p, Op.ACCEPT, ResourceScope(p.tenant_id, case_id, category))
        check_transition("review", r["review_state"], decision)
        sep = require_independent_review(str(r["actor_id"]), p.actor_id,
                                         self_review_allowed=self_review_allowed)
        c.execute("UPDATE claim_revisions SET review_state=%s, reviewed_at=clock_timestamp(), reviewer_id=%s,"
                  "review_category=%s, self_review=%s WHERE claim_id=%s AND revision=%s",
                  (decision, p.actor_id, category, sep["self_review_recorded"], claim_id, revision))
        c.execute("INSERT INTO claim_review_log(tenant_id,claim_id,revision,state,actor_id,category,self_review) "
                  "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                  (p.tenant_id, claim_id, revision, decision, p.actor_id, category, sep["self_review_recorded"]))
        ev = {"ACCEPTED": "claim.accepted", "WITHDRAWN": "claim.withdrawn"}.get(decision, f"claim.{decision.lower()}")
        emit_event(c, p, case_id=case_id, aggregate_id=claim_id, revision=revision, event_type=ev,
                   payload_refs=[{"kind": "claim", "id": claim_id, "revision": revision}], origin=r["origin"])
        audit(c, p, "claim.review", claim_id, {"revision": revision, "decision": decision,
                                               "category": category, **sep})
    return sep


_ASKNOWN = """
SELECT * FROM (
  SELECT DISTINCT ON (r.claim_id) r.claim_id, r.revision, r.predicate, r.proposition, r.value,
         r.epistemic_state, r.valid_from, r.valid_to, r.recorded_at, r.origin, s.state AS review_state
  FROM claim_revisions r
  JOIN LATERAL (SELECT l.state FROM claim_review_log l
                WHERE l.tenant_id=r.tenant_id AND l.claim_id=r.claim_id AND l.revision=r.revision
                  AND l.at <= %(cutoff)s AND l.state IN ('ACCEPTED','WITHDRAWN','REJECTED')
                ORDER BY l.at DESC, l.id DESC LIMIT 1) s ON true
  WHERE r.case_id=%(case)s AND r.recorded_at <= %(cutoff)s AND s.state IN ('ACCEPTED','WITHDRAWN')
  ORDER BY r.claim_id, r.revision DESC) t
WHERE review_state='ACCEPTED'
  AND (valid_from IS NULL OR %(vt)s::timestamptz IS NULL OR valid_from <= %(vt)s)
  AND (valid_to   IS NULL OR %(vt)s::timestamptz IS NULL OR %(vt)s < valid_to)
"""


def as_known_claims(p: Principal, case_id: str, cutoff: datetime, valid_instant: datetime | None = None) -> list[dict]:
    """Accepted claims as the system knew them at `cutoff` (from the append-only review log), optionally
    valid at `valid_instant` (half-open interval)."""
    authorize(p, Op.READ, ResourceScope(p.tenant_id, case_id))
    with tenant_tx(p.tenant_id) as c:
        rows = c.execute(_ASKNOWN, {"case": case_id, "cutoff": cutoff, "vt": valid_instant}).fetchall()
    return [r for r in rows if r["revision"] is not None]


# ---------------- snapshots ----------------
def create_snapshot(p: Principal, case_id: str, cutoff: datetime | None = None) -> str:
    authorize(p, Op.PROPOSE, ResourceScope(p.tenant_id, case_id))
    cutoff = cutoff or datetime.now(timezone.utc)
    with tenant_tx(p.tenant_id) as c:
        rows = sorted(c.execute(_ASKNOWN, {"case": case_id, "cutoff": cutoff, "vt": None}).fetchall(),
                      key=lambda r: str(r["claim_id"]))
        members = [(str(r["claim_id"]), r["revision"]) for r in rows]
        sid = _u()
        h = hashlib.sha256(_canon({"case": case_id, "cutoff": cutoff.isoformat(), "members": members,
                                   "schema": "1.0"}).encode()).hexdigest()
        c.execute("INSERT INTO world_snapshots(id,tenant_id,case_id,knowledge_cutoff,schema_version,content_hash) "
                  "VALUES (%s,%s,%s,%s,'1.0',%s)", (sid, p.tenant_id, case_id, cutoff, h))
        for cl, rev in members:
            c.execute("INSERT INTO snapshot_members(tenant_id,snapshot_id,claim_id,revision) VALUES (%s,%s,%s,%s)",
                      (p.tenant_id, sid, cl, rev))
        case = c.execute("SELECT origin FROM cases WHERE id=%s", (case_id,)).fetchone()
        emit_event(c, p, case_id=case_id, aggregate_id=sid, revision=1, event_type="snapshot.created",
                   payload_refs=[{"kind": "snapshot", "id": sid, "revision": 1}], origin=case["origin"])
    return sid


# ---------------- budgets (SRS-024, AT-017 part) ----------------
def create_budget(p: Principal, case_id: str, resource: str, limit_amount: int) -> str:
    authorize(p, Op.SET_ENVELOPE, ResourceScope(p.tenant_id, case_id))
    bid = _u()
    with tenant_tx(p.tenant_id) as c:
        c.execute("INSERT INTO budget_accounts(id,tenant_id,case_id,resource,limit_amount) VALUES (%s,%s,%s,%s,%s)",
                  (bid, p.tenant_id, case_id, resource, limit_amount))
        audit(c, p, "budget.create", bid, {"resource": resource, "limit": limit_amount})
    return bid


def reserve(p: Principal, account_id: str, amount: int, task_key: str) -> str | None:
    """Atomic: succeeds only if reserved+consumed+amount <= limit. Idempotent per task_key.
    Returns reservation id, or None when exhausted (caller must not dispatch)."""
    if amount <= 0:
        raise ValidationFailed(["amount must be positive"])
    with tenant_tx(p.tenant_id) as c:
        prev = c.execute("SELECT id FROM budget_reservations WHERE account_id=%s AND task_key=%s",
                         (account_id, task_key)).fetchone()
        if prev:
            return str(prev["id"])
        ok = c.execute("UPDATE budget_accounts SET reserved=reserved+%s "
                       "WHERE id=%s AND reserved+consumed+%s <= limit_amount RETURNING id",
                       (amount, account_id, amount)).fetchone()
        if not ok:
            return None
        rid = _u()
        c.execute("INSERT INTO budget_reservations(id,tenant_id,account_id,amount,task_key) VALUES (%s,%s,%s,%s,%s)",
                  (rid, p.tenant_id, account_id, amount, task_key))
        return rid


def settle(p: Principal, reservation_id: str, actual: int | None, *, unknown_outcome: bool = False) -> None:
    """Settle with actual usage; unknown billing outcome stays reserved (never silently released)."""
    with tenant_tx(p.tenant_id) as c:
        r = c.execute("SELECT account_id, amount, state FROM budget_reservations WHERE id=%s FOR UPDATE",
                      (reservation_id,)).fetchone()
        if not r:
            raise NotFound("reservation not found")
        if r["state"] != "RESERVED":
            raise Conflict(f"reservation already {r['state']}")
        if unknown_outcome:
            c.execute("UPDATE budget_reservations SET state='UNKNOWN_OUTCOME' WHERE id=%s", (reservation_id,))
            return
        if actual is None or actual < 0:
            raise ValidationFailed(["actual usage required"])
        extra = max(actual - r["amount"], 0)
        # overrun beyond reservation must still fit the limit, else record as failure to keep invariants
        res = c.execute("UPDATE budget_accounts SET reserved=reserved-%s, consumed=consumed+%s "
                        "WHERE id=%s AND reserved-%s>=0 AND (reserved-%s)+(consumed+%s)<=limit_amount RETURNING id",
                        (r["amount"], actual, r["account_id"], r["amount"], r["amount"], actual)).fetchone()
        if not res:
            raise Conflict("settlement would exceed budget limit")
        c.execute("UPDATE budget_reservations SET state='SETTLED', settled_amount=%s WHERE id=%s",
                  (actual, reservation_id))
