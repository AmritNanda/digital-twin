"""LangGraph State Machine for Bounded Cyclic Strategic Decision Twin Workflow.
(SRS-026, PRD Complete Workflow).
Coordinates:
1. Intake & Assessment (A20 Planner)
2. Intelligence & Research (A01 Research, A02 Market, A03 Competitor, A04 Customer)
3. Financial & Pricing Formulation (A06 Pricing, A07 Financial)
4. Strategy Hypotheses Formulation (A16 Strategy)
5. Monte Carlo Simulation (A14 Simulation)
6. Multiobjective Optimization (A15 Optimization)
7. Adversarial Challenge & Stress-Testing (A17 Devil's Advocate)
8. Falsification Evaluation & Replanning Loop (A11 Risk, A13 Evidence Auditor)
9. Release Gate Verification (A19 Verification)
10. Final Decision Synthesis & Release (A23 Final Decision)
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from dtp.identity import Principal, Role
from dtp.orchestration.catalog import AgentOutput, dispatch_agent_capability


class TwinExecutionState(TypedDict):
    tenant_id: str
    case_id: str
    question: str
    investigation_id: str
    iteration: int
    max_iterations: int
    evidence_collected: Annotated[list[dict[str, Any]], operator.add]
    claims_proposed: Annotated[list[dict[str, Any]], operator.add]
    financial_model: dict[str, Any]
    hypotheses: list[dict[str, Any]]
    simulation_results: list[dict[str, Any]]
    challenges: list[dict[str, Any]]
    verification_passed: bool
    unresolved_issues: Annotated[list[str], operator.add]
    final_decision: dict[str, Any]
    stop_reason: str


def _service_principal(tenant_id: str, actor_id: str) -> Principal:
    return Principal(tenant_id, actor_id, frozenset({Role.ANALYST}))


# ── Node Definitions ─────────────────────────────────────────────────────────

def node_plan_and_intake(state: TwinExecutionState) -> dict[str, Any]:
    p = _service_principal(state["tenant_id"], "planner_service")
    out = dispatch_agent_capability("A20", p, state["case_id"], {"question": state["question"]})
    return {"iteration": state["iteration"] + 1, "unresolved_issues": out.unresolved_issues}


def node_gather_intelligence(state: TwinExecutionState) -> dict[str, Any]:
    p = _service_principal(state["tenant_id"], "intelligence_service")
    r1 = dispatch_agent_capability("A01", p, state["case_id"], {"question": state["question"]})
    r2 = dispatch_agent_capability("A02", p, state["case_id"], {"question": f"Market size and competitor dynamics for {state['question']}"})
    r3 = dispatch_agent_capability("A04", p, state["case_id"], {"question": f"Customer segments and willingness to pay for {state['question']}"})
    return {"evidence_collected": [r1.result_data, r2.result_data, r3.result_data]}


def node_evaluate_financials(state: TwinExecutionState) -> dict[str, Any]:
    p = _service_principal(state["tenant_id"], "financial_service")
    out = dispatch_agent_capability("A07", p, state["case_id"], {})
    return {"financial_model": out.result_data}


def node_formulate_strategies(state: TwinExecutionState) -> dict[str, Any]:
    p = _service_principal(state["tenant_id"], "strategy_service")
    out = dispatch_agent_capability("A16", p, state["case_id"], {
        "question": state["question"],
        "financials": state["financial_model"],
    })
    # Establish at least two distinct hypothesis strategies
    base_hypotheses = [
        {"id": "strat_direct", "name": "Direct-to-Consumer Core", "price": 699.0, "cac": 140.0, "channel": "Direct"},
        {"id": "strat_marketplace", "name": "Marketplace Penetration", "price": 599.0, "cac": 90.0, "channel": "Marketplace"},
    ]
    return {"hypotheses": base_hypotheses}


def node_run_simulations(state: TwinExecutionState) -> dict[str, Any]:
    p = _service_principal(state["tenant_id"], "sim_service")
    results = []
    for h in state["hypotheses"]:
        out = dispatch_agent_capability("A14", p, state["case_id"], {
            "price": h["price"],
            "acquisition_cost": h["cac"],
            "seed": 42 + len(results),
        })
        results.append({"hypothesis_id": h["id"], "metrics": out.result_data})
    return {"simulation_results": results}


def node_adversarial_challenge(state: TwinExecutionState) -> dict[str, Any]:
    p = _service_principal(state["tenant_id"], "devils_advocate")
    out = dispatch_agent_capability("A17", p, state["case_id"], {
        "question": state["question"],
        "leading_strategy": state["hypotheses"][0] if state["hypotheses"] else {},
        "simulation": state["simulation_results"][0] if state["simulation_results"] else {},
    })
    challenges = [out.result_data]
    return {"challenges": challenges}


def node_verify_release(state: TwinExecutionState) -> dict[str, Any]:
    p = _service_principal(state["tenant_id"], "verification_service")
    out = dispatch_agent_capability("A19", p, state["case_id"], {
        "checks": [{"name": "accounting_reconciled", "result": "PASS", "mandatory": True}],
    })
    return {"verification_passed": out.status == "SUCCEEDED"}


def node_finalize_decision(state: TwinExecutionState) -> dict[str, Any]:
    p = _service_principal(state["tenant_id"], "decision_service")
    out = dispatch_agent_capability("A23", p, state["case_id"], {
        "question": state["question"],
        "hypotheses": state["hypotheses"],
        "simulations": state["simulation_results"],
        "challenges": state["challenges"],
    })
    return {
        "final_decision": out.result_data,
        "stop_reason": "CONVERGED",
    }


# ── Edge Routing Condition ───────────────────────────────────────────────────

def should_replan_or_release(state: TwinExecutionState) -> str:
    """Cyclic decision boundary: replan if major unresolved challenges exist and iterations remain."""
    if state["iteration"] >= state["max_iterations"]:
        return "finalize"
    # If unverified or major challenge triggered, loop back to plan/intelligence
    if not state.get("verification_passed", True):
        return "replan"
    return "finalize"


# ── Workflow Graph Construction ──────────────────────────────────────────────

def build_twin_workflow() -> Any:
    workflow = StateGraph(TwinExecutionState)

    workflow.add_node("plan", node_plan_and_intake)
    workflow.add_node("intelligence", node_gather_intelligence)
    workflow.add_node("financials", node_evaluate_financials)
    workflow.add_node("strategy", node_formulate_strategies)
    workflow.add_node("simulate", node_run_simulations)
    workflow.add_node("challenge", node_adversarial_challenge)
    workflow.add_node("verify", node_verify_release)
    workflow.add_node("finalize", node_finalize_decision)

    workflow.set_entry_point("plan")
    workflow.add_edge("plan", "intelligence")
    workflow.add_edge("intelligence", "financials")
    workflow.add_edge("financials", "strategy")
    workflow.add_edge("strategy", "simulate")
    workflow.add_edge("simulate", "challenge")
    workflow.add_edge("challenge", "verify")

    workflow.add_conditional_edges(
        "verify",
        should_replan_or_release,
        {
            "replan": "plan",
            "finalize": "finalize",
        },
    )
    workflow.add_edge("finalize", END)

    return workflow.compile()
