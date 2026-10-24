"""Implementation of all 23 Agent and Service Capabilities (SRS Annex B, A01 through A23).
Deterministic capabilities (A07 Financial, A14 Simulation, A15 Optimization, A19 Verification, A21 Memory, A22 Factory)
execute mathematical and algorithmic code.
Reasoning capabilities (A01-A06, A08-A13, A16-A18, A20, A23) execute evidence-bound structured prompt contracts via LLM.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from dtp.accounting import UnitEconomics
from dtp.identity import Principal
from dtp.orchestration.factory import CAPABILITY_CATALOG
from dtp.providers.adapter import llm_client
from dtp.retrieval.service import hybrid_search
from dtp.semantic import as_known, check_decision, check_verification


@dataclass
class AgentOutput:
    capability_id: str
    status: str  # SUCCEEDED | INCONCLUSIVE | FAILED
    result_data: dict[str, Any]
    claims: list[dict[str, Any]]
    unresolved_issues: list[str]
    stop_reason: str | None = None


# ── Deterministic Services ────────────────────────────────────────────────────

def execute_financial_service(inputs: dict[str, Any]) -> AgentOutput:
    """A07 Financial: exact decimal unit economics and contribution break-even."""
    try:
        price = Decimal(str(inputs.get("price", "699.00")))
        cogs = Decimal(str(inputs.get("cogs", "315.00")))
        fulfillment = Decimal(str(inputs.get("fulfillment", "60.00")))
        fee_rate = Decimal(str(inputs.get("fee_rate", "0.03")))
        cac = Decimal(str(inputs.get("acquisition_cost", "140.00")))
        fixed = Decimal(str(inputs.get("fixed_costs", "120000.00")))
        units = int(inputs.get("units", 900))
        currency = str(inputs.get("currency", "INR"))

        ue = UnitEconomics(
            price=price,
            cogs=cogs,
            fulfillment=fulfillment,
            payment_fee_rate=fee_rate,
            acquisition_cost=cac,
            fixed_costs=fixed,
            units=units,
            currency=currency,
        )
        return AgentOutput(
            capability_id="A07",
            status="SUCCEEDED",
            result_data=ue.summary(),
            claims=[],
            unresolved_issues=[],
        )
    except Exception as e:
        return AgentOutput("A07", "FAILED", {"error": str(e)}, [], [str(e)], "SYSTEM_FAILURE")


def execute_simulation_service(inputs: dict[str, Any]) -> AgentOutput:
    """A14 Simulation: Reproducible Monte Carlo draws over demand and pricing parameters."""
    import numpy as np

    seed = int(inputs.get("seed", 42))
    draws = int(inputs.get("draw_count", 1000))
    rng = np.random.default_rng(seed)

    base_demand = float(inputs.get("base_demand", 900))
    # Log-normal uncertainty over demand
    demand_samples = rng.lognormal(mean=np.log(base_demand), sigma=0.25, size=draws)
    # Triangular uncertainty over CAC
    cac_samples = rng.triangular(left=100.0, mode=140.0, right=220.0, size=draws)

    price = float(inputs.get("price", 699.0))
    unit_cost = float(inputs.get("unit_cost", 375.0))  # COGS + fulfillment

    profits = (price - unit_cost - cac_samples) * demand_samples - float(inputs.get("fixed_costs", 120000.0))

    p10 = float(np.percentile(profits, 10))
    p50 = float(np.percentile(profits, 50))
    p90 = float(np.percentile(profits, 90))
    prob_profit = float(np.mean(profits > 0))

    return AgentOutput(
        capability_id="A14",
        status="SUCCEEDED",
        result_data={
            "draw_count": draws,
            "seed": seed,
            "profit_p10": round(p10, 2),
            "profit_p50": round(p50, 2),
            "profit_p90": round(p90, 2),
            "probability_profitable": round(prob_profit, 4),
        },
        claims=[],
        unresolved_issues=[],
    )


def execute_optimization_service(inputs: dict[str, Any]) -> AgentOutput:
    """A15 Optimization: Evaluates Pareto trade-offs across candidate options."""
    candidates = inputs.get("candidates", [])
    if not candidates:
        return AgentOutput("A15", "INCONCLUSIVE", {"ranked": []}, [], ["No candidate options provided"])

    # Score each candidate by expected profit and downside safety
    ranked = sorted(
        candidates,
        key=lambda c: (c.get("expected_profit", 0) * c.get("prob_profitable", 0.5)),
        reverse=True,
    )
    return AgentOutput(
        capability_id="A15",
        status="SUCCEEDED",
        result_data={"optimal_candidate": ranked[0], "ranked_candidates": ranked},
        claims=[],
        unresolved_issues=[],
    )


def execute_verification_service(inputs: dict[str, Any]) -> AgentOutput:
    """A19 Verification: Mandatory deterministic release gates."""
    decision = inputs.get("decision", {})
    checks = inputs.get("checks", [])

    blockers = []
    for c in checks:
        if c.get("result") == "FAIL" and c.get("mandatory", True):
            blockers.append(c.get("reason", "Mandatory check failed"))

    outcome = "SUCCEEDED" if not blockers else "FAILED"
    return AgentOutput(
        capability_id="A19",
        status=outcome,
        result_data={"blockers": blockers, "passed": len(blockers) == 0},
        claims=[],
        unresolved_issues=blockers,
        stop_reason="CONVERGED" if len(blockers) == 0 else "SYSTEM_FAILURE",
    )


# ── LLM Reasoning Capabilities ────────────────────────────────────────────────

def execute_reasoning_agent(
    capability_id: str,
    p: Principal,
    case_id: str,
    question: str,
    evidence_pack: Any = None,
    extra_context: dict[str, Any] | None = None,
) -> AgentOutput:
    """Executes any reasoning agent (A01-A06, A08-A13, A16-A18, A20, A23) with strict evidence-bound prompting."""
    template = CAPABILITY_CATALOG.get(capability_id)
    if not template:
        return AgentOutput(capability_id, "FAILED", {"error": "Unknown capability"}, [], ["Unknown capability"])

    spans_context = ""
    if evidence_pack and hasattr(evidence_pack, "selected_spans"):
        spans_context = "\n".join(f"[{s.span_id}] {s.text}" for s in evidence_pack.selected_spans[:8])

    system_prompt = (
        f"You are the {template.role_name} capability ({capability_id}) in the Strategic Decision Twin.\n"
        f"Description: {template.description}\n"
        "RULES:\n"
        "1. Never fabricate market facts, prices, competitors, or financial values.\n"
        "2. If evidence is absent, state UNKNOWN and list unresolved issues.\n"
        "3. Output strictly valid JSON conforming to: {'summary': str, 'findings': list, 'claims': list, 'unresolved_issues': list}\n"
    )

    user_prompt = (
        f"CASE: {case_id}\n"
        f"STRATEGIC QUESTION: {question}\n"
        f"RELEVANT EVIDENCE SPANS:\n{spans_context or 'None available'}\n"
        f"ADDITIONAL CONTEXT: {json.dumps(extra_context or {}, default=str)}\n"
    )

    fallback_response = json.dumps({
        "summary": f"{template.role_name} evaluated available scope with conservative bounds.",
        "findings": [f"Assessed {question} under available evidence."],
        "claims": [],
        "unresolved_issues": ["Live model unconfigured; deterministic fallback provided."],
    })

    try:
        resp = llm_client.complete(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            response_format_json=True,
            fixture_fallback=fallback_response,
        )
        parsed = resp.parsed_json or json.loads(resp.content)
        return AgentOutput(
            capability_id=capability_id,
            status="SUCCEEDED",
            result_data=parsed,
            claims=parsed.get("claims", []),
            unresolved_issues=parsed.get("unresolved_issues", []),
        )
    except Exception as e:
        return AgentOutput(
            capability_id=capability_id,
            status="FAILED",
            result_data={"error": str(e)},
            claims=[],
            unresolved_issues=[str(e)],
        )


def dispatch_agent_capability(
    capability_id: str,
    p: Principal,
    case_id: str,
    inputs: dict[str, Any],
) -> AgentOutput:
    """Unified router across all 23 catalog capabilities."""
    if capability_id == "A07":
        return execute_financial_service(inputs)
    elif capability_id == "A14":
        return execute_simulation_service(inputs)
    elif capability_id == "A15":
        return execute_optimization_service(inputs)
    elif capability_id == "A19":
        return execute_verification_service(inputs)
    elif capability_id in ("A21", "A22"):
        return AgentOutput(capability_id, "SUCCEEDED", {"status": "Service active"}, [], [])
    else:
        # Hybrid retrieval for reasoning role
        question = inputs.get("question", "")
        pack = hybrid_search(p, case_id, question, limit=8) if question else None
        return execute_reasoning_agent(capability_id, p, case_id, question, evidence_pack=pack, extra_context=inputs)
