"""The prototype workflow must never turn missing verification into a decision."""

from types import SimpleNamespace

from dtp.identity import Principal, Role
from dtp.orchestration import catalog
from dtp.orchestration.catalog import dispatch_agent_capability, execute_verification_service
from dtp.orchestration.workflow import should_replan_or_release


def test_verification_requires_checks_that_pass():
    assert execute_verification_service({"checks": []}).status == "FAILED"
    assert execute_verification_service({"checks": [{"name": "source", "result": "UNKNOWN"}]}).status == "FAILED"
    assert execute_verification_service({"checks": [{"name": "source", "result": "PASS"}]}).status == "SUCCEEDED"


def test_unverified_work_does_not_reach_decision_node():
    state = {"verification_passed": False}
    assert should_replan_or_release(state) == "blocked"


def test_placeholder_capabilities_do_not_claim_success():
    principal = Principal("tenant", "actor", frozenset({Role.ANALYST}))
    assert dispatch_agent_capability("A21", principal, "case", {}).status == "INCONCLUSIVE"
    assert dispatch_agent_capability("A22", principal, "case", {}).status == "INCONCLUSIVE"


def test_offline_reasoning_is_marked_inconclusive(monkeypatch):
    response = SimpleNamespace(
        parsed_json={"summary": "unknown", "claims": [], "unresolved_issues": ["No live model"]},
        usage=SimpleNamespace(model="FIXTURE_MOCK"),
    )
    monkeypatch.setattr(catalog.llm_client, "complete", lambda **kwargs: response)
    principal = Principal("tenant", "actor", frozenset({Role.ANALYST}))
    assert catalog.execute_reasoning_agent("A20", principal, "case", "What next?").status == "INCONCLUSIVE"
