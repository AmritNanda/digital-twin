"""Acceptance tests for Stage 11 (Continuous Loop, Invalidation, Calibration) and Stage 12 (Action Gateway).

Verifies:
- AT-035: Watchers skip needless LLM invocations when content is unchanged; invalidation marks decisions STALE
- AT-036: Experiment origin isolation: synthetic observations cannot update real experiment calibration
- AT-045: Model recalibration rejected when holdout performance worsens
- AT-047: External action gateway: approval hash verification, tampered payload rejection, idempotency, and timeout reconciliation
"""
import sys
import time
import uuid
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.dtp import repo
from backend.dtp.identity import Principal, Role
from backend.dtp.watchers.service import WatcherService
from backend.dtp.experiments.service import (
    ExperimentService,
    SyntheticDataContaminationError,
    RecalibrationRegressionError,
)
from backend.dtp.gateway.service import (
    ActionGateway,
    ActionStatus,
    ApprovalHashMismatchError,
)
from backend.dtp.release.service import ReleaseService, DecisionOutcome, DecisionStatus
from backend.dtp.release.verification import VerificationService


@pytest.fixture
def env():
    tid, owner_id = repo.bootstrap_tenant("loop_tenant", f"owner_{time.time_ns()}@twin.test")
    p = Principal(
        tenant_id=tid,
        actor_id=owner_id,
        roles=frozenset({Role.OWNER, Role.ANALYST, Role.RESEARCH_OPERATOR}),
    )
    case_id = repo.create_case(
        p=p,
        title="Stage 11 & 12 Loop and Gateway Test Case",
        objective="Validate continuous loop and gateway",
        horizon_days=90,
        origin="FIXTURE",
    )
    return {"principal": p, "case_id": case_id}


def test_at035_watchers_change_detection_and_invalidation(env):
    """AT-035: Watcher skips expensive LLM analysis when source content is unchanged,
    and dependency invalidation marks decisions STALE immediately.
    """
    p = env["principal"]
    case_id = env["case_id"]
    w_svc = WatcherService()
    r_svc = ReleaseService()
    v_svc = VerificationService()

    # 1. Release an initial decision
    valid_payload = {
        "economics": {
            "price": "699.00", "cogs": "315.00", "fulfillment": "60.00",
            "payment_fee_rate": "0.03", "acquisition_cost": "140.00",
            "fixed_costs": "120000.00", "units": 900, "profit": "26727.00"
        },
        "citations": [{"id": "cite-001"}],
    }
    lineage = {
        "nodes": [{"id": "src", "kind": "source"}, {"id": "dec", "kind": "decision"}],
        "edges": [{"from": "src", "to": "dec", "role": "support"}],
    }
    rep = v_svc.verify_decision_draft(p, case_id, {"kind": "decision"}, valid_payload)
    draft = r_svc.create_decision_draft(p, case_id, DecisionOutcome.RECOMMEND, {}, valid_payload, lineage, verification_report_id=rep.id)
    r_svc.release_decision(p, case_id, draft.id)
    curr = r_svc.get_current_decision(p, case_id)
    assert curr.status == DecisionStatus.RELEASED

    # 2. Create watcher and poll with static content
    watcher = w_svc.create_watcher(p, case_id, "Competitor Price Watcher", "WEB_SCRAPER")
    
    # First poll: new content -> changed
    res1 = w_svc.poll_source(p, watcher.id, lambda: "Competitor Price: $699")
    assert res1.has_changed is True
    assert res1.llm_invoked is True

    # Second poll with identical content: unchanged -> skips LLM work!
    res2 = w_svc.poll_source(p, watcher.id, lambda: "Competitor Price: $699")
    assert res2.has_changed is False
    assert res2.llm_invoked is False
    assert "expensive analysis skipped" in res2.message

    # 3. Third poll with updated price: changed -> triggers invalidation
    res3 = w_svc.poll_source(p, watcher.id, lambda: "Competitor Price: $599 (Discount)")
    assert res3.has_changed is True

    # Invalidate decisions depending on competitor price
    stale_decs = w_svc.invalidate_dependencies(p, case_id, ["competitor_price"])
    assert draft.id in stale_decs

    # Current decision is now STALE
    curr_after = r_svc.get_current_decision(p, case_id)
    assert curr_after.status == DecisionStatus.STALE


def test_at036_experiment_origin_isolation(env):
    """AT-036: Synthetic observations cannot be imported into a REAL experiment cohort."""
    p = env["principal"]
    case_id = env["case_id"]
    e_svc = ExperimentService()

    # Create REAL experiment
    exp = e_svc.create_experiment(
        principal=p,
        case_id=case_id,
        title="Real Conversion Lift Study",
        hypothesis="Free delivery badge increases conversion by 2%",
        target_metric="conversion_rate",
        origin="REAL",
    )

    # Ingesting real observations succeeds
    real_data = [{"user_id": "u1", "converted": 1}, {"user_id": "u2", "converted": 0}]
    count = e_svc.ingest_observations(p, exp.id, real_data, data_origin="REAL")
    assert count == 2

    # Ingesting synthetic data into REAL experiment raises SyntheticDataContaminationError
    synthetic_data = [{"user_id": "synth-01", "converted": 1}]
    with pytest.raises(SyntheticDataContaminationError) as exc_info:
        e_svc.ingest_observations(p, exp.id, synthetic_data, data_origin="SYNTHETIC")
    assert "synthetic data prohibited from updating real calibration" in str(exc_info.value)


def test_at045_prospective_model_calibration(env):
    """AT-045: Candidate model recalibration rejected when holdout performance worsens."""
    e_svc = ExperimentService()

    # Case 1: Candidate improves holdout error (MAE drops from 0.15 to 0.11) -> Promoted
    eval_good = e_svc.evaluate_model_calibration(
        baseline_holdout_mae=0.15,
        candidate_holdout_mae=0.11,
    )
    assert eval_good["promoted"] is True
    assert eval_good["improvement"] > 0

    # Case 2: Candidate worsens holdout error (MAE rises from 0.15 to 0.19) -> Rejected
    with pytest.raises(RecalibrationRegressionError) as exc_info:
        e_svc.evaluate_model_calibration(
            baseline_holdout_mae=0.15,
            candidate_holdout_mae=0.19,
        )
    assert "holdout error worsened" in str(exc_info.value)


def test_at047_external_action_gateway(env):
    """AT-047: Action gateway verifies approval hash, detects tampered payloads,
    and supports idempotency and timeout UNKNOWN reconciliation.
    """
    p = env["principal"]
    case_id = env["case_id"]
    gw = ActionGateway()

    action_payload = {
        "channel": "google_ads",
        "campaign_id": "cmp-101",
        "daily_budget_cents": 50000,
    }

    idemp_key = f"idemp-{uuid.uuid4().hex[:8]}"

    # 1. Request approval and get cryptographic hash
    receipt = gw.request_action_approval(
        principal=p,
        case_id=case_id,
        action_type="UPDATE_CAMPAIGN_BUDGET",
        payload=action_payload,
        idempotency_key=idemp_key,
    )
    assert receipt.status == ActionStatus.PENDING
    assert receipt.approval_hash is not None

    # Idempotent re-request returns identical record
    receipt_idem = gw.request_action_approval(
        principal=p,
        case_id=case_id,
        action_type="UPDATE_CAMPAIGN_BUDGET",
        payload=action_payload,
        idempotency_key=idemp_key,
    )
    assert receipt_idem.id == receipt.id

    # 2. Tampered execution payload (budget raised to 999999) fails execution
    tampered_payload = {
        "channel": "google_ads",
        "campaign_id": "cmp-101",
        "daily_budget_cents": 999999, # Tampered!
    }
    with pytest.raises(ApprovalHashMismatchError) as exc_info:
        gw.execute_action(
            principal=p,
            action_id=receipt.id,
            execution_payload=tampered_payload,
            external_executor=lambda p: ("SUCCESS", {"ext_id": "ext-1"}),
        )
    assert "does not match approved hash" in str(exc_info.value)

    # 3. Timeout handling: transitions to UNKNOWN
    def timing_out_executor(p):
        raise TimeoutError("Sandbox gateway connection timed out")

    receipt_timeout = gw.execute_action(
        principal=p,
        action_id=receipt.id,
        execution_payload=action_payload, # original valid payload
        external_executor=timing_out_executor,
    )
    assert receipt_timeout.status == ActionStatus.UNKNOWN
    assert "transitioning to UNKNOWN" in receipt_timeout.execution_receipt["error"]
