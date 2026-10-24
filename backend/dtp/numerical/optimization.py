"""Pareto multi-objective optimization and hard constraint solver (SRS-037, AT-026, AT-029).

Enforces:
- Hard constraints are never converted to soft penalties; candidate status returned before rank
- Candidate A with highest profit but violating hard constraints is marked infeasible and NOT recommended (AT-026)
- If all actions are infeasible, returns ALL_INFEASIBLE with blocking constraints identified (AT-029)
- Non-dominated sorting produces explicit Pareto frontier
- Multi-objective ties within indifference tolerance are reported explicitly without inventing utility weights
- Global optimum certificates are never fabricated for heuristic searches
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Any

CENT = Decimal("0.01")


class OptimizationStatus(str, Enum):
    FEASIBLE_RECOMMENDATION = "FEASIBLE_RECOMMENDATION"
    ALL_INFEASIBLE = "ALL_INFEASIBLE"
    MULTI_OBJECTIVE_TIED = "MULTI_OBJECTIVE_TIED"
    SUBOPTIMAL_HEURISTIC = "SUBOPTIMAL_HEURISTIC"


@dataclass
class ConstraintEvaluation:
    name: str
    passed: bool
    actual_value: Decimal
    limit_value: Decimal
    operator: str
    is_hard: bool = True
    blocking_reason: Optional[str] = None


@dataclass
class CandidateAction:
    action_id: str
    name: str
    parameters: Dict[str, Any]
    is_baseline_or_defer: bool = False
    
    # Evaluated outcomes
    profit: Decimal = Decimal("0.00")
    min_cash: Decimal = Decimal("0.00")
    cvar_loss: Decimal = Decimal("0.00")
    units: int = 0
    extra_metrics: Dict[str, Any] = field(default_factory=dict)
    
    # Feasibility
    is_feasible: bool = True
    constraint_evaluations: List[ConstraintEvaluation] = field(default_factory=list)
    blocking_constraints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "name": self.name,
            "is_baseline_or_defer": self.is_baseline_or_defer,
            "is_feasible": self.is_feasible,
            "profit": str(self.profit.quantize(CENT, ROUND_HALF_UP)),
            "min_cash": str(self.min_cash.quantize(CENT, ROUND_HALF_UP)),
            "cvar_loss": str(self.cvar_loss.quantize(CENT, ROUND_HALF_UP)),
            "units": self.units,
            "blocking_constraints": self.blocking_constraints,
        }


@dataclass
class HardConstraint:
    name: str
    description: str
    evaluator: Callable[[CandidateAction], ConstraintEvaluation]


@dataclass
class OptimizationResult:
    status: OptimizationStatus
    recommended_action: Optional[CandidateAction]
    feasible_candidates: List[CandidateAction]
    infeasible_candidates: List[CandidateAction]
    pareto_frontier: List[CandidateAction]
    blocking_constraints_by_action: Dict[str, List[str]]
    indifference_tied_actions: List[CandidateAction]
    is_conditional_scenario: bool
    global_optimum_claimed: bool
    termination_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "recommended_action": self.recommended_action.to_dict() if self.recommended_action else None,
            "feasible_count": len(self.feasible_candidates),
            "infeasible_count": len(self.infeasible_candidates),
            "pareto_count": len(self.pareto_frontier),
            "blocking_constraints": self.blocking_constraints_by_action,
            "indifference_tied_count": len(self.indifference_tied_actions),
            "is_conditional_scenario": self.is_conditional_scenario,
            "global_optimum_claimed": self.global_optimum_claimed,
            "termination_reason": self.termination_reason,
        }


class OptimizationSolver:
    """Evaluates candidate actions against hard constraints and determines the Pareto frontier."""

    def __init__(
        self,
        hard_constraints: List[HardConstraint],
        primary_objective: str = "profit",
        secondary_objective: Optional[str] = "min_cash",
        indifference_tolerance: Decimal = Decimal("50.00"),
        is_conditional_scenario: bool = True,
    ):
        self.hard_constraints = hard_constraints
        self.primary_objective = primary_objective
        self.secondary_objective = secondary_objective
        self.indifference_tolerance = Decimal(indifference_tolerance)
        self.is_conditional_scenario = is_conditional_scenario

    def _evaluate_candidate_constraints(self, candidate: CandidateAction) -> None:
        candidate.constraint_evaluations.clear()
        candidate.blocking_constraints.clear()
        is_feasible = True

        for c in self.hard_constraints:
            ev = c.evaluator(candidate)
            candidate.constraint_evaluations.append(ev)
            if not ev.passed:
                is_feasible = False
                candidate.blocking_constraints.append(ev.blocking_reason or ev.name)

        candidate.is_feasible = is_feasible

    def solve(self, candidates: List[CandidateAction]) -> OptimizationResult:
        if not candidates:
            raise ValueError("Candidates list cannot be empty")

        # 1. Evaluate hard constraints for every candidate BEFORE ranking (AT-026)
        feasible: List[CandidateAction] = []
        infeasible: List[CandidateAction] = []
        blocking_by_action: Dict[str, List[str]] = {}

        for cand in candidates:
            self._evaluate_candidate_constraints(cand)
            if cand.is_feasible:
                feasible.append(cand)
            else:
                infeasible.append(cand)
                blocking_by_action[cand.action_id] = cand.blocking_constraints

        # 2. Check all-infeasible set (AT-029)
        if not feasible:
            # Baseline/defer candidate check
            baseline = next((c for c in candidates if c.is_baseline_or_defer), None)
            return OptimizationResult(
                status=OptimizationStatus.ALL_INFEASIBLE,
                recommended_action=None,
                feasible_candidates=[],
                infeasible_candidates=infeasible,
                pareto_frontier=[],
                blocking_constraints_by_action=blocking_by_action,
                indifference_tied_actions=[],
                is_conditional_scenario=self.is_conditional_scenario,
                global_optimum_claimed=False,
                termination_reason="All candidate actions violate one or more hard constraints (SRS-037, AT-029)",
            )

        # 3. Compute Pareto Frontier among feasible candidates
        pareto_frontier: List[CandidateAction] = []
        for i, a in enumerate(feasible):
            is_dominated = False
            for j, b in enumerate(feasible):
                if i != j:
                    # b dominates a if b is at least as good in all objectives and strictly better in at least one
                    # Objectives: profit (maximize), min_cash (maximize), cvar_loss (minimize)
                    b_better_or_eq = (
                        b.profit >= a.profit
                        and b.min_cash >= a.min_cash
                        and b.cvar_loss <= a.cvar_loss
                    )
                    b_strictly_better = (
                        b.profit > a.profit
                        or b.min_cash > a.min_cash
                        or b.cvar_loss < a.cvar_loss
                    )
                    if b_better_or_eq and b_strictly_better:
                        is_dominated = True
                        break
            if not is_dominated:
                pareto_frontier.append(a)

        # 4. Rank feasible candidates by primary objective
        feasible.sort(key=lambda c: getattr(c, self.primary_objective), reverse=True)
        best = feasible[0]

        # 5. Check for multi-objective ties within indifference tolerance (AT-029)
        tied_candidates: List[CandidateAction] = []
        for cand in feasible:
            diff = abs(getattr(best, self.primary_objective) - getattr(cand, self.primary_objective))
            if diff <= self.indifference_tolerance:
                tied_candidates.append(cand)

        status = OptimizationStatus.FEASIBLE_RECOMMENDATION
        if len(tied_candidates) > 1:
            status = OptimizationStatus.MULTI_OBJECTIVE_TIED

        return OptimizationResult(
            status=status,
            recommended_action=best,
            feasible_candidates=feasible,
            infeasible_candidates=infeasible,
            pareto_frontier=pareto_frontier,
            blocking_constraints_by_action=blocking_by_action,
            indifference_tied_actions=tied_candidates if len(tied_candidates) > 1 else [],
            is_conditional_scenario=self.is_conditional_scenario,
            global_optimum_claimed=False, # SRS-037: heuristic result must not claim global optimality
            termination_reason="Solved finite candidate enumeration under hard constraints",
        )
