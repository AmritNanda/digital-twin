"""Stage 7 & 8 integration tests: Factory, All 23 Capability Catalog items, and Bounded Cyclic LangGraph Workflow.
"""
from __future__ import annotations

import time
import pytest

from dtp import repo
from dtp.identity import Principal, Role
from dtp.orchestration import (
    CAPABILITY_CATALOG,
    admit_agent_instance,
    build_twin_workflow,
    dispatch_agent_capability,
)
from dtp.tasks import create_investigation, submit_task


@pytest.fixture()
def orch_world():
    tid, owner_id = repo.bootstrap_tenant("orch_t", f"o{time.time_ns()}@orch.test")
    owner = Principal(tid, owner_id, frozenset({Role.OWNER}))
    case = repo.create_case(owner, title="Orchestration Case", objective="Launch strategy", horizon_days=90, origin="FIXTURE")
    snap = repo.create_snapshot(owner, case)
    inv = create_investigation(owner, case, snap, "Full System Run")
    return {"tid": tid, "owner": owner, "case": case, "snap": snap, "inv": inv}


def test_catalog_contains_all_23_capabilities():
    assert len(CAPABILITY_CATALOG) == 23
    expected_ids = {f"A{i:02d}" for i in range(1, 24)}
    assert set(CAPABILITY_CATALOG.keys()) == expected_ids


def test_agent_factory_admission_and_depth_limits(orch_world):
    owner = orch_world["owner"]
    case_id = orch_world["case"]
    inv_id = orch_world["inv"]

    task_id = submit_task(owner, case_id, inv_id, "A01", "Research task", delegation_depth=1)

    instance = admit_agent_instance(owner, task_id, "A01", max_depth=2)
    assert instance["status"] == "ADMITTED"
    assert instance["capability_id"] == "A01"
    assert "search" in instance["tool_allowlist"]


def test_deterministic_financial_and_simulation_services(orch_world):
    owner = orch_world["owner"]
    case_id = orch_world["case"]

    # A07 Financial
    fin = dispatch_agent_capability("A07", owner, case_id, {"price": "699.00", "cogs": "315.00"})
    assert fin.status == "SUCCEEDED"
    assert fin.result_data["fee_per_unit"] is not None

    # A14 Simulation
    sim = dispatch_agent_capability("A14", owner, case_id, {"draw_count": 500, "seed": 123})
    assert sim.status == "SUCCEEDED"
    assert sim.result_data["draw_count"] == 500
    assert "profit_p50" in sim.result_data


def test_langgraph_full_twin_workflow_execution(orch_world):
    owner = orch_world["owner"]
    case_id = orch_world["case"]
    inv_id = orch_world["inv"]
    tid = orch_world["tid"]

    app = build_twin_workflow()

    initial_state = {
        "tenant_id": tid,
        "case_id": case_id,
        "question": "What price point and channel should we launch our modular kitchen storage starter kit?",
        "investigation_id": inv_id,
        "iteration": 0,
        "max_iterations": 2,
        "evidence_collected": [],
        "claims_proposed": [],
        "financial_model": {},
        "hypotheses": [],
        "simulation_results": [],
        "challenges": [],
        "verification_passed": True,
        "unresolved_issues": [],
        "final_decision": {},
        "stop_reason": "",
    }

    final_state = app.invoke(initial_state)

    assert final_state["iteration"] >= 1
    assert len(final_state["hypotheses"]) >= 2
    assert len(final_state["simulation_results"]) >= 2
    assert len(final_state["challenges"]) > 0
    assert final_state["stop_reason"] == "CONVERGED"
    assert "summary" in final_state["final_decision"]
