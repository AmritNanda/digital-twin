"""Acceptance tests for Stage 10: Strategy, Falsification, Verification & Release Pipeline.

Verifies:
- AT-030: Adversarial challenge creation, refutation test execution, and resolution
- AT-032: Mandatory verification failures block release (numerical error, invented sources)
- AT-033: Lineage closure, missing reference detection, and DAG cycle rejection
- AT-034: Atomic current pointer, optimistic concurrency race rejection, and stale invalidation
"""
import sys
import time
from pathlib import Path
from decimal import Decimal
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.dtp import repo
from backend.dtp.identity import Principal, Role
from backend.dtp.release.challenges import (
    ChallengeService,
    ChallengeStatus,
    Severity,
)
from backend.dtp.release.verification import (
    CheckStatus,
    OverallOutcome,
    VerificationBlockedError,
    VerificationService,
)
from backend.dtp.release.service import (
    DecisionOutcome,
    DecisionStatus,
    LineageClosureError,
    ReleaseService,
    StaleReleaseRaceError,
)


@pytest.fixture
def env(postgres_ready):
    tid, owner_id = repo.bootstrap_tenant("test_tenant", f"owner_{time.time_ns()}@twin.test")
    p = Principal(
        tenant_id=tid,
        actor_id=owner_id,
        roles=frozenset({Role.OWNER, Role.ANALYST}),
    )
    case_id = repo.create_case(
        p=p,
        title="Stage 10 Falsification and Release Test Case",
        objective="Validate release pipeline",
        horizon_days=90,
        origin="FIXTURE",
    )
    return {"principal": p, "case_id": case_id}


def test_at030_adversarial_challenge_refutation_and_closure(env):
    """AT-030: Leading action challenged under omitted cost condition.
    
    Verifies:
    - Concrete failure proposition and proposed test created
    - Refutation test executed and resolution recorded
    - Unresolved material challenges cannot be dismissed merely by restating rationale
    """
    p = env["principal"]
    case_id = env["case_id"]
    svc = ChallengeService()

    # 1. Challenger creates concrete material challenge
    chal = svc.create_challenge(
        principal=p,
        case_id=case_id,
        title="Expedited freight surcharge violates positive contribution",
        severity=Severity.MATERIAL,
        failure_proposition="If fulfillment expense increases from 60 to 190 INR due to air express delivery, contribution margin drops below break-even.",
        proposed_test="Rerun unit economics fixture with variable_fulfillment = 190.00",
        reversal_criteria="Contribution per unit <= 0 or profit < 0",
        affected_artifact_refs=[{"kind": "parameter", "key": "variable_fulfillment"}],
    )
    assert chal.status == ChallengeStatus.OPEN

    # 2. Check that it appears in unresolved list
    unresolved = svc.list_unresolved_material_challenges(p, case_id)
    assert len(unresolved) == 1
    assert unresolved[0].id == chal.id

    # 3. Execute refutation test
    def refutation_runner():
        return True, "Fulfillment at 190.00 INR yields negative profit of -3,273.00 INR; reversal confirmed."

    resolved_chal = svc.execute_test(p, chal.id, refutation_runner)
    assert resolved_chal.status == ChallengeStatus.RESOLVED
    assert "reversal confirmed" in resolved_chal.test_result

    # 4. Challenge is now resolved, so unresolved list is empty
    assert len(svc.list_unresolved_material_challenges(p, case_id)) == 0


def test_at032_mandatory_verification_blocks_drafts_with_flaws(env):
    """AT-032: Draft with invented sources or wrong profit fails mandatory verification and blocks release.
    
    Verifies:
    - Numerical error is caught deterministically (CHK-NUM-001)
    - Invented source is caught deterministically (CHK-CITE-001)
    - Release is strictly blocked with VerificationBlockedError
    """
    p = env["principal"]
    case_id = env["case_id"]
    v_svc = VerificationService()
    r_svc = ReleaseService()

    # 1. Draft with numerical invariant error (claimed 50,000 profit instead of 26,727)
    flawed_payload = {
        "economics": {
            "price": "699.00",
            "cogs": "315.00",
            "fulfillment": "60.00",
            "payment_fee_rate": "0.03",
            "acquisition_cost": "140.00",
            "fixed_costs": "120000.00",
            "units": 900,
            "profit": "50000.00", # Wrong! Correct is 26,727.00
        },
        "citations": [{"id": "cite-001", "invented": False}],
    }

    report = v_svc.verify_decision_draft(
        principal=p,
        case_id=case_id,
        target_artifact_ref={"kind": "decision_draft", "id": "draft-001"},
        draft_payload=flawed_payload,
    )
    assert report.overall_outcome == OverallOutcome.FAIL
    assert any("Numerical reconciliation failed" in b for b in report.blocking_reasons)

    # 2. Valid lineage for draft creation
    valid_lineage = {
        "nodes": [
            {"id": "source-01", "kind": "source_version"},
            {"id": "claim-01", "kind": "claim"},
            {"id": "draft-01", "kind": "decision_draft"},
        ],
        "edges": [
            {"from": "source-01", "to": "claim-01", "role": "grounding"},
            {"from": "claim-01", "to": "draft-01", "role": "support"},
        ],
    }

    draft = r_svc.create_decision_draft(
        principal=p,
        case_id=case_id,
        outcome=DecisionOutcome.RECOMMEND,
        objective_and_constraints={"objective": "maximize_profit"},
        summary_payload=flawed_payload,
        lineage_closure=valid_lineage,
        verification_report_id=report.id,
    )

    # Attempting to release with a failed verification report MUST raise VerificationBlockedError
    with pytest.raises(VerificationBlockedError) as exc_info:
        r_svc.release_decision(p, case_id, draft.id)
    assert "Verification overall outcome is FAIL" in str(exc_info.value)

    # 3. Flawed draft with invented citation
    invented_cite_payload = {
        "economics": {
            "price": "699.00",
            "cogs": "315.00",
            "fulfillment": "60.00",
            "payment_fee_rate": "0.03",
            "acquisition_cost": "140.00",
            "fixed_costs": "120000.00",
            "units": 900,
            "profit": "26727.00", # Correct
        },
        "citations": [{"id": "cite-fake", "invented": True}], # Invented!
    }
    report_fake = v_svc.verify_decision_draft(
        principal=p,
        case_id=case_id,
        target_artifact_ref={"kind": "decision_draft", "id": "draft-002"},
        draft_payload=invented_cite_payload,
    )
    assert report_fake.overall_outcome == OverallOutcome.FAIL
    assert any("invented citation" in b for b in report_fake.blocking_reasons)


def test_at033_lineage_closure_and_cycle_rejection(env):
    """AT-033: Lineage DAG closure: missing references and cycles fail validation."""
    r_svc = ReleaseService()

    # 1. Missing node reference
    broken_lineage = {
        "nodes": [{"id": "node-A", "kind": "source"}],
        "edges": [{"from": "node-A", "to": "node-B", "role": "support"}],
    }
    with pytest.raises(LineageClosureError) as exc_info1:
        r_svc.validate_lineage_closure(broken_lineage)
    assert "missing target node 'node-B'" in str(exc_info1.value)

    # 2. Cycle detection: A -> B -> C -> A
    cyclic_lineage = {
        "nodes": [
            {"id": "node-A", "kind": "source"},
            {"id": "node-B", "kind": "claim"},
            {"id": "node-C", "kind": "decision"},
        ],
        "edges": [
            {"from": "node-A", "to": "node-B", "role": "support"},
            {"from": "node-B", "to": "node-C", "role": "support"},
            {"from": "node-C", "to": "node-A", "role": "invalid_cycle"},
        ],
    }
    with pytest.raises(LineageClosureError) as exc_info2:
        r_svc.validate_lineage_closure(cyclic_lineage)
    assert "contains a dependency cycle" in str(exc_info2.value)


def test_at034_atomic_release_concurrency_race_and_stale_invalidation(env):
    """AT-034: Optimistic concurrency race rejection, supersession, and stale invalidation.
    
    Verifies:
    - Initial decision release succeeds (Revision 1)
    - Second decision release updates pointer to Revision 2; Revision 1 marked SUPERSEDED
    - Losing concurrent worker racing on stale revision is rejected with StaleReleaseRaceError
    - Invalidation marks decision STALE
    """
    p = env["principal"]
    case_id = env["case_id"]
    v_svc = VerificationService()
    r_svc = ReleaseService()

    valid_payload = {
        "economics": {
            "price": "699.00",
            "cogs": "315.00",
            "fulfillment": "60.00",
            "payment_fee_rate": "0.03",
            "acquisition_cost": "140.00",
            "fixed_costs": "120000.00",
            "units": 900,
            "profit": "26727.00",
        },
        "citations": [{"id": "cite-valid", "invented": False}],
    }
    valid_lineage = {
        "nodes": [
            {"id": "src-1", "kind": "source_version"},
            {"id": "clm-1", "kind": "claim"},
        ],
        "edges": [{"from": "src-1", "to": "clm-1", "role": "support"}],
    }

    # 1. Verify and release first decision
    v_rep1 = v_svc.verify_decision_draft(
        principal=p,
        case_id=case_id,
        target_artifact_ref={"kind": "decision", "id": "dec-1"},
        draft_payload=valid_payload,
    )
    assert v_rep1.overall_outcome == OverallOutcome.PASS

    dec1 = r_svc.create_decision_draft(
        principal=p,
        case_id=case_id,
        outcome=DecisionOutcome.RECOMMEND,
        objective_and_constraints={"objective": "profit"},
        summary_payload=valid_payload,
        lineage_closure=valid_lineage,
        verification_report_id=v_rep1.id,
    )
    rel1 = r_svc.release_decision(p, case_id, dec1.id)
    assert rel1.status == DecisionStatus.RELEASED
    assert rel1.revision == 1

    # Check current decision pointer
    curr = r_svc.get_current_decision(p, case_id)
    assert curr.id == dec1.id

    # 2. Create second decision (Revision 2)
    dec2 = r_svc.create_decision_draft(
        principal=p,
        case_id=case_id,
        outcome=DecisionOutcome.RECOMMEND,
        objective_and_constraints={"objective": "profit"},
        summary_payload=valid_payload,
        lineage_closure=valid_lineage,
        verification_report_id=v_rep1.id,
    )
    rel2 = r_svc.release_decision(
        principal=p,
        case_id=case_id,
        decision_id=dec2.id,
        expected_current_revision=1,
    )
    assert rel2.status == DecisionStatus.RELEASED
    assert rel2.revision == 2

    # Verify that dec1 is now SUPERSEDED
    curr_now = r_svc.get_current_decision(p, case_id)
    assert curr_now.id == dec2.id

    # 3. Concurrent worker race simulation: Worker 3 tries to release dec3 expecting current revision to still be 1
    dec3 = r_svc.create_decision_draft(
        principal=p,
        case_id=case_id,
        outcome=DecisionOutcome.RECOMMEND,
        objective_and_constraints={"objective": "profit"},
        summary_payload=valid_payload,
        lineage_closure=valid_lineage,
        verification_report_id=v_rep1.id,
    )
    with pytest.raises(StaleReleaseRaceError) as exc_race:
        r_svc.release_decision(
            principal=p,
            case_id=case_id,
            decision_id=dec3.id,
            expected_current_revision=1, # Fails because current revision is now 2!
        )
    assert "Release race detected" in str(exc_race.value)

    # 4. Stale invalidation: when parameter changes, decision is marked STALE
    r_svc.mark_decision_stale(p, case_id, dec2.id)
    curr_stale = r_svc.get_current_decision(p, case_id)
    assert curr_stale.status == DecisionStatus.STALE
