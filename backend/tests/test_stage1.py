"""Stage 1 tests. Covers SRS-004, 015, 033, Annex C/D; AT-003(part), 006, 007, 023, 033(part), 038(part).
All data is FIXTURE."""
import copy
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dtp import capabilities, semantic
from dtp.accounting import CurrencyMismatch, Money, UnitEconomics
from dtp.contracts import ContractError, load_fixture_examples, strict_loads, validate_artifact
from dtp.identity import (AuthorizationError, DevSession, NotFound, Op, Principal,
                          ResourceScope, Role, authorize, require_independent_review)
from dtp.lifecycle import IllegalTransition, check_transition

T1, T2, C1 = "t-1", "t-2", "case-1"


# ---------- contracts ----------
@pytest.mark.parametrize("ex", load_fixture_examples(), ids=lambda e: e["artifact_type"])
def test_fixture_examples_are_schema_valid(ex):
    validate_artifact(ex)


def test_additional_fields_rejected():
    ex = copy.deepcopy(load_fixture_examples()[0])
    ex["hidden_grant"] = "admin"
    with pytest.raises(ContractError):
        validate_artifact(ex)


def test_strict_json_rejects_nan_and_duplicates():
    with pytest.raises(ContractError):
        strict_loads('{"a": NaN}')
    with pytest.raises(ContractError):
        strict_loads('{"a": 1, "a": 2}')


def test_unknown_type_rejected():
    with pytest.raises(ContractError):
        validate_artifact({"artifact_type": "Nope"})


# ---------- accounting (AT-023) ----------
def base():
    return UnitEconomics(Decimal("699"), Decimal("315"), Decimal("60"), Decimal("0.03"),
                         Decimal("140"), Decimal("120000"), 900, "INR")


def test_golden_base():
    s = base().summary()
    assert s["fee_per_unit"] == Decimal("20.97")
    assert s["contribution_per_unit"] == Decimal("163.03")
    assert s["break_even_units"] == 737
    assert s["profit"] == Decimal("26727.00")


def test_golden_acquisition_stress():
    s = base().with_acquisition_cost(Decimal("196")).summary()
    assert s["contribution_per_unit"] == Decimal("107.03")
    assert s["break_even_units"] == 1122
    assert s["profit"] == Decimal("-23673.00")


def test_max_cac_exact_and_feasibility_not_rounded():
    e = base()
    assert abs(e.max_cac_for_zero_profit - Decimal("169.6966667")) < Decimal("0.0000001")
    assert e.feasible_at_cac(Decimal("169.69"))
    assert not e.feasible_at_cac(Decimal("169.70"))  # displayed rounding must not flip result


def test_no_finite_breakeven_when_contribution_nonpositive():
    assert base().with_acquisition_cost(Decimal("400")).break_even_units is None


def test_cross_currency_blocked():
    with pytest.raises(CurrencyMismatch):
        Money(1, "INR") + Money(1, "USD")


# ---------- lifecycle ----------
def test_decision_cannot_become_fresh_in_place():
    check_transition("decision", "RELEASED", "STALE")
    with pytest.raises(IllegalTransition):
        check_transition("decision", "STALE", "RELEASED")
    with pytest.raises(IllegalTransition):
        check_transition("decision", "DRAFT", "RELEASED")  # must be verified


def test_terminal_task_never_reopens():
    with pytest.raises(IllegalTransition):
        check_transition("task_attempt", "SUCCEEDED", "RUNNING")


def test_action_unknown_needs_reconciliation():
    with pytest.raises(IllegalTransition):
        check_transition("action", "UNKNOWN", "SUCCEEDED")
    check_transition("action", "UNKNOWN", "SUCCEEDED", reconciled=True)
    with pytest.raises(IllegalTransition):
        check_transition("action", "DISPATCHING", "DRAFT")


# ---------- identity (AT-006, AT-038 part) ----------
def P(roles, tenant=T1, **kw):
    return Principal(tenant, "u1", frozenset(roles), **kw)


def test_cross_tenant_is_not_found():
    with pytest.raises(NotFound):
        authorize(P({Role.OWNER}), Op.READ, ResourceScope(T2, C1))


def test_reader_cannot_propose_admin_cannot_read_without_grant():
    rs = ResourceScope(T1, C1)
    with pytest.raises(AuthorizationError):
        authorize(P({Role.READER}, case_ids=frozenset({C1})), Op.PROPOSE, rs)
    with pytest.raises(AuthorizationError):
        authorize(P({Role.ADMINISTRATOR}), Op.READ, rs)
    authorize(P({Role.ADMINISTRATOR}, grants=frozenset({(Op.READ, "*")})), Op.READ, rs)


def test_action_approval_needs_category_grant_even_for_owner():
    rs = ResourceScope(T1, C1, "price_change")
    with pytest.raises(AuthorizationError):
        authorize(P({Role.OWNER}), Op.APPROVE_ACTION, rs)
    authorize(P({Role.OWNER}, grants=frozenset({(Op.APPROVE_ACTION, "price_change")})),
              Op.APPROVE_ACTION, rs)
    with pytest.raises(AuthorizationError):  # wrong category
        authorize(P({Role.OWNER}, grants=frozenset({(Op.APPROVE_ACTION, "email")})),
                  Op.APPROVE_ACTION, rs)


def test_admin_deploy_rights_do_not_confer_acceptance():
    with pytest.raises(AuthorizationError):
        authorize(P({Role.ADMINISTRATOR}), Op.ACCEPT, ResourceScope(T1, C1, "financial"))


def test_reviewer_scoped_to_assigned_case_and_category():
    p = P({Role.DOMAIN_REVIEWER}, case_ids=frozenset({C1}), grants=frozenset({(Op.ACCEPT, "legal")}))
    authorize(p, Op.ACCEPT, ResourceScope(T1, C1, "legal"))
    with pytest.raises(AuthorizationError):
        authorize(p, Op.ACCEPT, ResourceScope(T1, C1, "financial"))
    with pytest.raises(AuthorizationError):
        authorize(p, Op.READ, ResourceScope(T1, "other-case"))


def test_explicit_deny_and_revocation():
    rs = ResourceScope(T1, C1)
    with pytest.raises(AuthorizationError):
        authorize(P({Role.OWNER}, denies=frozenset({(Op.READ, "*")})), Op.READ, rs)
    with pytest.raises(AuthorizationError):
        authorize(P({Role.OWNER}, revoked=True), Op.READ, rs)


def test_self_review_is_recorded_not_independent():
    with pytest.raises(AuthorizationError):
        require_independent_review("a", "a")
    r = require_independent_review("a", "a", self_review_allowed=True)
    assert r == {"independent": False, "self_review_recorded": True}


def test_dev_session_requires_token_loopback_and_origin():
    s = DevSession("tok-abc", P({Role.OWNER}))
    assert s.check("tok-abc", None, "127.0.0.1").actor_id == "u1"
    for args in (("bad", None, "127.0.0.1"), (None, None, "127.0.0.1"),
                 ("tok-abc", "https://evil.example", "127.0.0.1"), ("tok-abc", None, "10.0.0.5")):
        with pytest.raises(AuthorizationError):
            s.check(*args)


# ---------- semantic ----------
def test_distribution_rules():
    assert semantic.check_distribution({"family": "TRIANGULAR", "low": 1, "mode": 5, "high": 3})
    assert semantic.check_distribution({"family": "UNIFORM", "low": 3, "high": 3})
    assert not semantic.check_distribution({"family": "BETA", "alpha": 2, "beta": 3})


def test_unknown_with_value_and_known_without_evidence_fail():
    ex = next(e for e in load_fixture_examples() if e["artifact_type"] == "ClaimProposal")
    assert semantic.check_claim({**ex, "epistemic_state": "UNKNOWN"})
    assert semantic.check_claim({**ex, "epistemic_state": "KNOWN", "evidence_refs": []})
    assert semantic.check_claim({**ex, "epistemic_state": "CONTRADICTED", "competing_claim_refs": []})


def test_as_known_excludes_future_correction():
    recs = [
        {"id": "c", "revision": 1, "recorded_at": "2026-01-10T00:00:00Z", "value": 100,
         "scope": {"valid_from": "2025-01-01T00:00:00Z", "valid_to": "2025-06-01T00:00:00Z"}},
        {"id": "c", "revision": 2, "recorded_at": "2026-03-01T00:00:00Z", "value": 120,
         "scope": {"valid_from": "2025-01-01T00:00:00Z", "valid_to": "2025-06-01T00:00:00Z"}},
    ]
    early = semantic.as_known(recs, "2026-02-01T00:00:00Z")
    late = semantic.as_known(recs, "2026-04-01T00:00:00Z")
    assert [r["value"] for r in early] == [100] and [r["value"] for r in late] == [120]
    # half-open: valid_to instant excluded
    assert not semantic.as_known(recs, "2026-04-01T00:00:00Z", "2025-06-01T00:00:00Z")
    assert semantic.as_known(recs, "2026-04-01T00:00:00Z", "2025-05-31T23:59:59Z")


def test_fixture_cannot_become_real():
    assert semantic.check_origin(["REAL", "FIXTURE"], "REAL")
    assert not semantic.check_origin(["FIXTURE"], "FIXTURE")


def test_metric_availability():
    base_m = {"key": "profit", "unit": "INR", "currency": "INR"}
    assert semantic.check_metric({**base_m, "availability": "AVAILABLE", "value": float("nan"), "reason": None})
    assert semantic.check_metric({**base_m, "availability": "UNAVAILABLE", "value": 0, "reason": "x"})
    assert semantic.check_metric({**base_m, "availability": "UNAVAILABLE", "value": None, "reason": None})
    assert not semantic.check_metric({**base_m, "availability": "UNAVAILABLE", "value": None, "reason": "no data"})


def test_causal_counterfactual_needs_identified_model():
    ex = next(e for e in load_fixture_examples() if e["artifact_type"] == "ScenarioPatch")
    causal = {**ex, "semantic_type": "CAUSAL_COUNTERFACTUAL"}
    assert semantic.check_scenario(causal, allowed_keys=frozenset(), identified_models=frozenset())
    assert not semantic.check_scenario({**ex, "semantic_type": "SENSITIVITY"},
                                       allowed_keys=frozenset(p.get("parameter_key") or p.get("key") for p in ex["patches"]))


def test_decision_recommend_blocked_on_failed_verification():
    d = next(e for e in load_fixture_examples() if e["artifact_type"] == "DecisionProposal")
    d = {**d, "outcome": "RECOMMEND", "selected_strategy_ref": {"kind": "strategy", "id": "s1", "revision": 1}}
    assert semantic.check_decision(d, feasible_strategy_ids=frozenset({"s1"}),
                                   verification_failed=True, definitive_gates_passed=False)
    assert semantic.check_decision(d, feasible_strategy_ids=frozenset(),  # infeasible pick
                                   verification_failed=False, definitive_gates_passed=True)
    assert not semantic.check_decision({**d, "stop_reason": "NEEDS_INPUT", "unresolved_issues": []},
                                       feasible_strategy_ids=frozenset({"s1"}),
                                       verification_failed=False, definitive_gates_passed=True)


def test_lineage_cycle_detected():
    assert not semantic.check_no_cycles([("a", "b"), ("b", "c")])
    assert semantic.check_no_cycles([("a", "b"), ("b", "c"), ("c", "a")])


# ---------- capabilities ----------
def test_capabilities_unconfigured_without_leaking_values():
    st = {c["id"]: c for c in capabilities.status({})}
    assert st["llm.openai_compatible"]["state"] == "UNCONFIGURED"
    assert st["db.postgres"]["state"] == "NOT_IMPLEMENTED"
    cfg = capabilities.status({"LLM_BASE_URL": "u", "LLM_API_KEY": "SECRETVALUE", "LLM_MODEL": "m"})
    assert "SECRETVALUE" not in repr(cfg)
    assert {c["id"]: c for c in cfg}["llm.openai_compatible"]["state"] == "CONFIGURED_UNVERIFIED"
