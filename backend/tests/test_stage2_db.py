"""Stage 2 integration tests against REAL PostgreSQL (docker compose). Skipped (not passed) if DB is
unreachable. Data is FIXTURE-origin. Covers SRS-004/015/016/020/024; AT-006,007,015(part),017(part),038(part)."""
import copy
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dtp import repo
from dtp.contracts import load_fixture_examples
from dtp.db import DbUnconfigured, app_conn, migrate, owner_conn, tenant_tx
from dtp.identity import AuthorizationError, NotFound, Op, Principal, Role
from dtp.lifecycle import IllegalTransition

try:
    migrate()
except (DbUnconfigured, psycopg.OperationalError) as e:  # pragma: no cover
    pytest.skip(f"PostgreSQL unavailable: {e}", allow_module_level=True)


def now():
    return datetime.now(timezone.utc)


def pause():
    time.sleep(0.05)


@pytest.fixture()
def world():
    tid, owner_id = repo.bootstrap_tenant("t", f"o{time.time_ns()}@fixture.test")
    analyst_id = repo.add_user(tid, f"a{time.time_ns()}@fixture.test", ["analyst"])
    reviewer_id = repo.add_user(tid, f"r{time.time_ns()}@fixture.test", ["domain_reviewer"])
    owner = Principal(tid, owner_id, frozenset({Role.OWNER}),
                      grants=frozenset({(Op.ACCEPT, "financial")}))
    analyst = Principal(tid, analyst_id, frozenset({Role.ANALYST}))
    reviewer_p = lambda cases: Principal(tid, reviewer_id, frozenset({Role.DOMAIN_REVIEWER}),
                                         case_ids=frozenset(cases), grants=frozenset({(Op.ACCEPT, "financial")}))
    case = repo.create_case(owner, title="c", objective="profit", horizon_days=90, origin="FIXTURE")
    return dict(tid=tid, owner=owner, analyst=analyst, reviewer=reviewer_p, case=case)


def claim_art(tid, **over):
    a = copy.deepcopy(next(e for e in load_fixture_examples() if e["artifact_type"] == "ClaimProposal"))
    a["tenant_id"] = tid
    a["origin"] = "FIXTURE"
    a.update(over)
    return a


# ---------- role / schema hygiene ----------
def test_migrations_idempotent_and_app_role_is_unprivileged():
    assert migrate() == []
    with owner_conn() as c:
        r = c.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='twin_app'").fetchone()
        assert r == {"rolsuper": False, "rolbypassrls": False}
        assert c.execute("SELECT count(*) n FROM pg_tables t JOIN pg_class k ON k.relname=t.tablename "
                         "WHERE schemaname='public' AND tablename='claim_revisions' AND NOT k.relforcerowsecurity"
                         ).fetchone()["n"] == 0


# ---------- tenancy (AT-038 part) ----------
def test_cross_tenant_reads_hidden_at_service_and_row_level(world):
    other_tid, other_owner = repo.bootstrap_tenant("other", f"x{time.time_ns()}@fixture.test")
    other = Principal(other_tid, other_owner, frozenset({Role.OWNER}))
    with pytest.raises(NotFound):
        repo.get_case(other, world["case"])
    # even a hand-written query under the other tenant sees nothing
    with tenant_tx(other_tid) as c:
        assert c.execute("SELECT count(*) n FROM cases WHERE id=%s", (world["case"],)).fetchone()["n"] == 0
    # no tenant context => nothing visible, and writes are refused
    with app_conn() as c:
        assert c.execute("SELECT count(*) n FROM cases").fetchone()["n"] == 0
    with pytest.raises(psycopg.Error):
        with tenant_tx(other_tid) as c:
            c.execute("INSERT INTO cases(id,tenant_id,title,country,currency,tax_basis,origin,created_by) "
                      "VALUES (gen_random_uuid(),%s,'x','US','USD','NET','FIXTURE',%s)",
                      (world["tid"], other_owner))


def test_payload_tenant_mismatch_rejected(world):
    art = claim_art(str(__import__("uuid").uuid4()))
    with pytest.raises(repo.ValidationFailed, match="tenant"):
        repo.propose_claim(world["analyst"], world["case"], art)


# ---------- claims, review, immutability ----------
def test_propose_review_flow_and_separation(world):
    cid, rev = repo.propose_claim(world["analyst"], world["case"], claim_art(world["tid"]))
    assert rev == 1
    # analyst has no accept grant (AT-006)
    with pytest.raises(AuthorizationError):
        repo.review_claim(world["analyst"], cid, 1, "ACCEPTED", category="financial")
    # owner proposing + accepting own claim is blocked unless explicitly allowed and then recorded
    cid2, _ = repo.propose_claim(world["owner"], world["case"], claim_art(world["tid"]))
    with pytest.raises(AuthorizationError):
        repo.review_claim(world["owner"], cid2, 1, "ACCEPTED", category="financial")
    sep = repo.review_claim(world["owner"], cid2, 1, "ACCEPTED", category="financial", self_review_allowed=True)
    assert sep == {"independent": False, "self_review_recorded": True}
    # wrong category / illegal transition
    with pytest.raises(AuthorizationError):
        repo.review_claim(world["owner"], cid, 1, "ACCEPTED", category="legal")
    repo.review_claim(world["owner"], cid, 1, "ACCEPTED", category="financial")
    with pytest.raises(IllegalTransition):
        repo.review_claim(world["owner"], cid, 1, "REJECTED", category="financial")


def test_unknown_with_value_and_non_proposed_rejected(world):
    from dtp.contracts import ContractError
    with pytest.raises((repo.ValidationFailed, ContractError)):
        repo.propose_claim(world["analyst"], world["case"], claim_art(world["tid"], epistemic_state="UNKNOWN"))
    with pytest.raises((repo.ValidationFailed, ContractError)):
        repo.propose_claim(world["analyst"], world["case"], claim_art(world["tid"], review_state="ACCEPTED"))


def test_db_enforces_immutability_and_guarded_transitions(world):
    cid, _ = repo.propose_claim(world["analyst"], world["case"], claim_art(world["tid"]))
    with pytest.raises(psycopg.Error):  # app role has no UPDATE privilege on payload columns
        with tenant_tx(world["tid"]) as c:
            c.execute("UPDATE claim_revisions SET proposition='tampered' WHERE claim_id=%s", (cid,))
    with pytest.raises(psycopg.Error):
        with tenant_tx(world["tid"]) as c:
            c.execute("DELETE FROM events")
    with pytest.raises(psycopg.Error):  # skipping review: PROPOSED -> WITHDRAWN illegal at DB level
        with tenant_tx(world["tid"]) as c:
            c.execute("UPDATE claim_revisions SET review_state='WITHDRAWN' WHERE claim_id=%s", (cid,))
    with pytest.raises(psycopg.Error):  # ACCEPTED without reviewer metadata refused
        with tenant_tx(world["tid"]) as c:
            c.execute("UPDATE claim_revisions SET review_state='ACCEPTED' WHERE claim_id=%s", (cid,))


# ---------- temporal as-known (AT-007) ----------
def test_as_known_excludes_future_correction(world):
    o, case, tid = world["owner"], world["case"], world["tid"]
    a = claim_art(tid, value={"type": "DECIMAL", "value": "100", "unit": "INR", "currency": "INR", "tax_basis": "NET"})
    cid, _ = repo.propose_claim(world["analyst"], case, a)
    repo.review_claim(o, cid, 1, "ACCEPTED", category="financial")
    pause(); t_between = now(); pause()
    b = claim_art(tid, value={"type": "DECIMAL", "value": "120", "unit": "INR", "currency": "INR", "tax_basis": "NET"})
    _, rev2 = repo.propose_claim(world["analyst"], case, b, claim_id=cid)
    assert rev2 == 2
    # unreviewed correction is not yet knowledge
    assert [r["revision"] for r in repo.as_known_claims(o, case, now())] == [1]
    repo.review_claim(o, cid, 2, "ACCEPTED", category="financial")
    assert [r["revision"] for r in repo.as_known_claims(o, case, now())] == [2]
    assert [r["revision"] for r in repo.as_known_claims(o, case, t_between)] == [1]  # future excluded
    assert repo.as_known_claims(o, case, datetime(2000, 1, 1, tzinfo=timezone.utc)) == []
    # old revision retained
    with tenant_tx(tid) as c:
        assert c.execute("SELECT count(*) n FROM claim_revisions WHERE claim_id=%s", (cid,)).fetchone()["n"] == 2


def test_withdrawn_claim_disappears_from_current_knowledge(world):
    o = world["owner"]
    cid, _ = repo.propose_claim(world["analyst"], world["case"], claim_art(world["tid"]))
    repo.review_claim(o, cid, 1, "ACCEPTED", category="financial")
    pause(); before = now(); pause()
    repo.review_claim(o, cid, 1, "WITHDRAWN", category="financial")
    assert repo.as_known_claims(o, world["case"], now()) == []
    assert len(repo.as_known_claims(o, world["case"], before)) == 1


# ---------- idempotency ----------
def test_idempotent_commands(world):
    a = claim_art(world["tid"])
    r1 = repo.propose_claim(world["analyst"], world["case"], a, idempotency_key="k1")
    r2 = repo.propose_claim(world["analyst"], world["case"], a, idempotency_key="k1")
    assert r1 == r2
    with pytest.raises(repo.Conflict):
        repo.propose_claim(world["analyst"], world["case"], claim_art(world["tid"], predicate="other"),
                           idempotency_key="k1")
    with tenant_tx(world["tid"]) as c:
        assert c.execute("SELECT count(*) n FROM claim_revisions WHERE claim_id=%s", (r1[0],)).fetchone()["n"] == 1


# ---------- case lifecycle ----------
def test_closed_case_rejects_new_proposals_and_illegal_transition(world):
    with pytest.raises(IllegalTransition):
        repo.transition_case(world["owner"], world["case"], "ARCHIVED")
    repo.transition_case(world["owner"], world["case"], "CLOSED")
    with pytest.raises(repo.Conflict):
        repo.propose_claim(world["analyst"], world["case"], claim_art(world["tid"]))


def test_fixture_case_rejects_real_claim(world):
    with pytest.raises(repo.ValidationFailed, match="FIXTURE"):
        repo.propose_claim(world["analyst"], world["case"], claim_art(world["tid"], origin="REAL"))


# ---------- outbox / events (AT-015 part) ----------
def test_outbox_survives_crash_and_consumers_deduplicate(world):
    o = world["owner"]
    repo.propose_claim(world["analyst"], world["case"], claim_art(world["tid"]))
    with tenant_tx(world["tid"]) as c:
        total = c.execute("SELECT count(*) n FROM outbox").fetchone()["n"]
    assert total >= 2  # case.created + claim.proposed committed atomically with state
    seen = []
    with pytest.raises(RuntimeError):
        repo.publish_pending(o, "graph", seen.append, crash_before_ack=True)
    with tenant_tx(world["tid"]) as c:  # crash: nothing acked, no receipt committed
        assert c.execute("SELECT count(*) n FROM outbox WHERE published_at IS NULL").fetchone()["n"] == total
        assert c.execute("SELECT count(*) n FROM consumer_receipts").fetchone()["n"] == 0
    seen.clear()
    assert repo.publish_pending(o, "graph", seen.append) == total
    assert len(seen) == total
    assert repo.publish_pending(o, "graph", seen.append) == 0  # nothing left
    # a different consumer is independent: its own receipts
    with tenant_tx(world["tid"]) as c:
        c.execute("UPDATE outbox SET published_at=NULL")
    again = []
    repo.publish_pending(o, "graph", again.append)           # replay: receipts suppress handler
    assert again == []
    other = []
    with tenant_tx(world["tid"]) as c:
        c.execute("UPDATE outbox SET published_at=NULL")
    repo.publish_pending(o, "search", other.append)
    assert len(other) == total


def test_event_ordering_by_aggregate_revision_is_unique(world):
    cid, _ = repo.propose_claim(world["analyst"], world["case"], claim_art(world["tid"]))
    with pytest.raises(psycopg.Error):  # duplicate (aggregate, revision, type) rejected
        with tenant_tx(world["tid"]) as c:
            repo.emit_event(c, world["analyst"], case_id=world["case"], aggregate_id=cid, revision=1,
                            event_type="claim.proposed", payload_refs=[], origin="FIXTURE")


# ---------- budgets (AT-017 part) ----------
def test_concurrent_reservations_never_exceed_limit(world):
    acct = repo.create_budget(world["owner"], world["case"], "CALLS", 10)
    results, lock = [], threading.Lock()

    def worker(i):
        r = repo.reserve(world["owner"], acct, 1, f"task-{i}")
        with lock:
            results.append(r)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sum(r is not None for r in results) == 10
    with tenant_tx(world["tid"]) as c:
        a = c.execute("SELECT reserved, consumed, limit_amount FROM budget_accounts WHERE id=%s", (acct,)).fetchone()
    assert a["reserved"] == 10 and a["reserved"] + a["consumed"] <= a["limit_amount"]


def test_reservation_idempotent_settle_and_unknown_outcome(world):
    acct = repo.create_budget(world["owner"], world["case"], "USD_MICROS", 1000)
    r1 = repo.reserve(world["owner"], acct, 400, "t1")
    assert repo.reserve(world["owner"], acct, 400, "t1") == r1  # same task key => same reservation
    r2 = repo.reserve(world["owner"], acct, 400, "t2")
    assert repo.reserve(world["owner"], acct, 400, "t3") is None  # would exceed
    repo.settle(world["owner"], r1, 300)
    repo.settle(world["owner"], r2, None, unknown_outcome=True)   # stays reserved
    with tenant_tx(world["tid"]) as c:
        a = c.execute("SELECT reserved, consumed FROM budget_accounts WHERE id=%s", (acct,)).fetchone()
    assert (a["reserved"], a["consumed"]) == (400, 300)
    assert repo.reserve(world["owner"], acct, 400, "t4") is None  # 400+300+400 > 1000
    assert repo.reserve(world["owner"], acct, 300, "t5") is not None
    with pytest.raises(repo.Conflict):
        repo.settle(world["owner"], r1, 300)


def test_analyst_cannot_set_budget(world):
    with pytest.raises(AuthorizationError):
        repo.create_budget(world["analyst"], world["case"], "CALLS", 5)
    with pytest.raises(psycopg.Error):  # DB CHECK: negative never possible even via raw SQL
        with tenant_tx(world["tid"]) as c:
            c.execute("INSERT INTO budget_accounts(id,tenant_id,case_id,resource,limit_amount,reserved) "
                      "VALUES (gen_random_uuid(),%s,%s,'CALLS',5,9)", (world["tid"], world["case"]))


# ---------- snapshots (SRS-015) ----------
def test_snapshot_pins_accepted_members_and_is_immutable(world):
    o, case, tid = world["owner"], world["case"], world["tid"]
    c1, _ = repo.propose_claim(world["analyst"], case, claim_art(tid))
    c2, _ = repo.propose_claim(world["analyst"], case, claim_art(tid, predicate="unreviewed"))
    repo.review_claim(o, c1, 1, "ACCEPTED", category="financial")
    pause()
    s1 = repo.create_snapshot(o, case)
    repo.propose_claim(world["analyst"], case, claim_art(tid, predicate="later"), claim_id=c1)
    repo.review_claim(o, c1, 2, "ACCEPTED", category="financial")
    s2 = repo.create_snapshot(o, case)
    with tenant_tx(tid) as c:
        m1 = c.execute("SELECT claim_id, revision FROM snapshot_members WHERE snapshot_id=%s", (s1,)).fetchall()
        m2 = c.execute("SELECT claim_id, revision FROM snapshot_members WHERE snapshot_id=%s", (s2,)).fetchall()
        h = c.execute("SELECT id, content_hash FROM world_snapshots WHERE id IN (%s,%s)", (s1, s2)).fetchall()
    assert [(str(r["claim_id"]), r["revision"]) for r in m1] == [(c1, 1)]   # unreviewed c2 excluded
    assert [(str(r["claim_id"]), r["revision"]) for r in m2] == [(c1, 2)]   # new snapshot, old untouched
    assert len({r["content_hash"] for r in h}) == 2
    for stmt in ("UPDATE world_snapshots SET content_hash='x'", "DELETE FROM snapshot_members"):
        with pytest.raises(psycopg.Error):
            with tenant_tx(tid) as c:
                c.execute(stmt)
