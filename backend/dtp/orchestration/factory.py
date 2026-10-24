"""Agent Factory, Templates, and Tool Gateway (A22, SRS-023, SRS-049).
Governs capability admission, tool permission boundaries, token/time limits, and instance life cycle.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from dtp.db import tenant_tx
from dtp.identity import AuthorizationError, NotFound, Op, Principal, ResourceScope, authorize
from dtp.lifecycle import check_transition


@dataclass(frozen=True)
class CapabilityTemplate:
    capability_id: str
    role_name: str
    version: str
    is_service: bool  # True if deterministic algorithmic code; False if LLM
    tool_allowlist: tuple[str, ...]
    max_tokens: int = 2048
    max_steps: int = 5
    description: str = ""


# Normative 23 capabilities (SRS Annex B)
CAPABILITY_CATALOG: dict[str, CapabilityTemplate] = {
    "A01": CapabilityTemplate("A01", "Research", "1.0", False, ("search", "read_span"), description="Targeted external/internal evidence resolution"),
    "A02": CapabilityTemplate("A02", "Market Intelligence", "1.0", False, ("query_knowledge", "read_span"), description="Industry size, trends, and market segments"),
    "A03": CapabilityTemplate("A03", "Competitor", "1.0", False, ("query_knowledge", "read_span"), description="Competitor offerings, positions, and pricing"),
    "A04": CapabilityTemplate("A04", "Customer Intelligence", "1.0", False, ("query_knowledge", "read_span"), description="Customer segment needs, willingness-to-pay, and cohorts"),
    "A05": CapabilityTemplate("A05", "Sentiment", "1.0", False, ("query_knowledge", "read_span"), description="Audience perception, sentiment trends, coverage caveats"),
    "A06": CapabilityTemplate("A06", "Pricing", "1.0", False, ("query_knowledge", "eval_price_elasticity"), description="Pricing tiers, elasticity curves, packaging"),
    "A07": CapabilityTemplate("A07", "Financial", "1.0", True, ("compute_unit_economics", "cash_flow_model"), description="Deterministic accounting, contribution margins, cash forecast"),
    "A08": CapabilityTemplate("A08", "Regulatory", "1.0", False, ("query_knowledge", "read_span"), description="Jurisdictional compliance, consumer protection, labeling"),
    "A09": CapabilityTemplate("A09", "Political & Geopolitical", "1.0", False, ("query_knowledge", "read_span"), description="Trade policies, tariffs, supply chain risks"),
    "A10": CapabilityTemplate("A10", "Technology", "1.0", False, ("query_knowledge", "read_span"), description="Platform capabilities, tech stack readiness, integration constraints"),
    "A11": CapabilityTemplate("A11", "Risk", "1.0", False, ("query_knowledge", "evaluate_downside"), description="Downside risk registers, operational vulnerabilities"),
    "A12": CapabilityTemplate("A12", "Bias Auditor", "1.0", False, ("audit_claims", "check_demographics"), description="Audits demographic gaps, sample bias, and over-extrapolation"),
    "A13": CapabilityTemplate("A13", "Evidence Auditor", "1.0", False, ("verify_entailment", "check_citations"), description="Checks citations for direct factual entailment"),
    "A14": CapabilityTemplate("A14", "Simulation", "1.0", True, ("run_monte_carlo", "sample_distributions"), description="Reproducible Monte Carlo draws and uncertainty modeling"),
    "A15": CapabilityTemplate("A15", "Optimization", "1.0", True, ("solve_pareto", "evaluate_constraints"), description="Multiobjective ranking, Pareto frontiers, constraint feasibility"),
    "A16": CapabilityTemplate("A16", "Strategy", "1.0", False, ("query_knowledge", "formulate_hypothesis"), description="Formulates competing hypotheses with distinct target actions"),
    "A17": CapabilityTemplate("A17", "Devil's Advocate", "1.0", False, ("query_knowledge", "create_falsification_test"), description="Active falsification, refutations, stress-testing leading options"),
    "A18": CapabilityTemplate("A18", "Experiment", "1.0", False, ("design_study", "power_analysis"), description="Designs real-world test plans, pre-registers sample criteria"),
    "A19": CapabilityTemplate("A19", "Verification", "1.0", True, ("check_mandatory_gates", "verify_accounting"), description="Deterministic release checks; blocks unverified release"),
    "A20": CapabilityTemplate("A20", "Planner", "1.0", False, ("admit_tasks", "evaluate_uncertainty"), description="Information-gain prioritization and graph execution planning"),
    "A21": CapabilityTemplate("A21", "Memory", "1.0", True, ("query_as_known", "read_snapshot"), description="As-known temporal queries and snapshot consistency checks"),
    "A22": CapabilityTemplate("A22", "Agent Factory", "1.0", True, ("admit_instance", "enforce_bounds"), description="Instantiates approved capability templates and enforces budget"),
    "A23": CapabilityTemplate("A23", "Final Decision", "1.0", False, ("synthesize_package", "disclose_assumptions"), description="Synthesizes release-ready decision package with assumptions & conditions"),
}


class AdmissionDenied(Exception):
    pass


def admit_agent_instance(
    p: Principal,
    task_id: str,
    capability_id: str,
    budget_reservation_id: str | None = None,
    max_depth: int = 2,
) -> dict[str, Any]:
    """Factory admission gate (A22, SRS-023). Validates template, tenant scope, and admission limits."""
    template = CAPABILITY_CATALOG.get(capability_id)
    if not template:
        raise AdmissionDenied(f"CAPABILITY_UNAVAILABLE: {capability_id} is not an approved catalog template")

    instance_id = str(uuid.uuid4())
    attempt_id = str(uuid.uuid4())

    with tenant_tx(p.tenant_id) as c:
        task = c.execute("SELECT case_id, delegation_depth, state FROM tasks WHERE id=%s", (task_id,)).fetchone()
        if not task:
            raise NotFound(f"Task {task_id} not found")

        if task["delegation_depth"] > max_depth:
            raise AdmissionDenied(f"Delegation depth {task['delegation_depth']} exceeds limit {max_depth}")

        # Check total active instances in investigation
        active_count = c.execute(
            """
            SELECT count(*) n FROM agent_instances i
            JOIN tasks t ON t.id = i.task_id
            WHERE t.case_id = %s AND i.state IN ('ADMITTED', 'RUNNING')
            """,
            (task["case_id"],),
        ).fetchone()["n"]

        if active_count >= 8:  # Enforces bounded small-investigation profile
            raise AdmissionDenied(f"Active instance limit reached ({active_count}/8). Wait for running instances to complete.")

        c.execute(
            """
            INSERT INTO agent_instances(id, tenant_id, task_id, attempt_id, capability_id, template_version, state, budget_reservation_id, fencing_token)
            VALUES (%s, %s, %s, %s, %s, %s, 'ADMITTED', %s, 1)
            """,
            (instance_id, p.tenant_id, task_id, attempt_id, capability_id, template.version, budget_reservation_id),
        )

    return {
        "instance_id": instance_id,
        "capability_id": capability_id,
        "role_name": template.role_name,
        "is_service": template.is_service,
        "tool_allowlist": list(template.tool_allowlist),
        "status": "ADMITTED",
    }
