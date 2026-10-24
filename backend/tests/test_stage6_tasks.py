"""Stage 6 integration tests: Durable Tasks, Leases, Fencing Tokens, and Scheduler (SRS-021, SRS-022, AT-016, AT-018, AT-042).
"""
from __future__ import annotations

import time
import pytest

from dtp import repo
from dtp.identity import Op, Principal, Role
from dtp.tasks import (
    StaleFencingToken,
    acquire_task_lease,
    commit_task_result,
    create_investigation,
    submit_task,
)


@pytest.fixture()
def task_world():
    tid, owner_id = repo.bootstrap_tenant("tasks_t", f"o{time.time_ns()}@tasks.test")
    owner = Principal(tid, owner_id, frozenset({Role.OWNER}))
    case = repo.create_case(owner, title="Tasks Case", objective="Execution", horizon_days=30, origin="FIXTURE")
    snap = repo.create_snapshot(owner, case)
    inv = create_investigation(owner, case, snap, "Initial Strategic Investigation")
    return {"tid": tid, "owner": owner, "case": case, "snap": snap, "inv": inv}


def test_task_fingerprint_deduplication(task_world):
    owner = task_world["owner"]
    case_id = task_world["case"]
    inv_id = task_world["inv"]

    t1 = submit_task(owner, case_id, inv_id, "A01_RESEARCH", "Investigate competitor pricing", [{"kind": "target", "id": "brand_x"}])
    t2 = submit_task(owner, case_id, inv_id, "A01_RESEARCH", "Investigate competitor pricing", [{"kind": "target", "id": "brand_x"}])

    # Deduplicated fingerprint in same investigation -> same task ID
    assert t1 == t2


def test_task_dependency_resolution(task_world):
    owner = task_world["owner"]
    case_id = task_world["case"]
    inv_id = task_world["inv"]

    # Prerequisite task
    dep_id = submit_task(owner, case_id, inv_id, "A01_RESEARCH", "Gather market reports")
    # Dependent task
    child_id = submit_task(owner, case_id, inv_id, "A14_SIMULATION", "Run demand simulation", dependency_task_ids=[dep_id])

    # Acquiring worker should get dep_id first, child_id is WAITING_DEPENDENCY
    w1 = acquire_task_lease(owner, "worker_1")
    assert w1 is not None
    assert w1["task_id"] == dep_id

    # No more ready tasks yet
    assert acquire_task_lease(owner, "worker_2") is None

    # Complete prerequisite
    commit_task_result(owner, w1["task_id"], w1["attempt_id"], w1["fencing_token"], "SUCCEEDED")

    # Now dependent task is ready
    w2 = acquire_task_lease(owner, "worker_2")
    assert w2 is not None
    assert w2["task_id"] == child_id


def test_stale_fencing_token_rejection(task_world):
    owner = task_world["owner"]
    case_id = task_world["case"]
    inv_id = task_world["inv"]

    task_id = submit_task(owner, case_id, inv_id, "A06_PRICING", "Evaluate price points")

    # Worker 1 acquires with 1 second lease
    w1 = acquire_task_lease(owner, "worker_slow", lease_seconds=1)
    assert w1 is not None
    assert w1["task_id"] == task_id

    time.sleep(1.2)  # Wait for lease expiration

    # Worker 2 acquires recovered lease (fencing token increments)
    w2 = acquire_task_lease(owner, "worker_fast", lease_seconds=30)
    assert w2 is not None
    assert w2["task_id"] == task_id
    assert w2["fencing_token"] > w1["fencing_token"]

    # Worker 1 comes back delayed and attempts to commit -> MUST be rejected (AT-042)
    with pytest.raises(StaleFencingToken):
        commit_task_result(owner, w1["task_id"], w1["attempt_id"], w1["fencing_token"], "SUCCEEDED")

    # Worker 2 commits successfully
    commit_task_result(owner, w2["task_id"], w2["attempt_id"], w2["fencing_token"], "SUCCEEDED")
