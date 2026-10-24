"""Scenario patches, sensitivities, and causal counterfactual validation (SRS-036, AT-028).

Enforces:
- Base snapshots are strictly immutable; patches spawn child snapshots
- Affected descendants recalculate while unaffected parameters remain preserved
- Causal counterfactuals require verified causal identification; without it, causal claims are strictly rejected (AT-028)
- Distinguishes SENSITIVITY, STRUCTURAL_INTERVENTION, and CAUSAL_COUNTERFACTUAL
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Dict, List, Optional, Any

from backend.dtp.accounting import UnitEconomics

CENT = Decimal("0.01")


class ScenarioType(str, Enum):
    SENSITIVITY = "SENSITIVITY"
    STRUCTURAL_INTERVENTION = "STRUCTURAL_INTERVENTION"
    CAUSAL_COUNTERFACTUAL = "CAUSAL_COUNTERFACTUAL"


class CausalIdentificationError(RuntimeError):
    """Raised when a causal counterfactual claim is asserted without an identified causal model (SRS-036, AT-028)."""
    pass


@dataclass
class ScenarioPatchModel:
    patch_id: str
    base_snapshot_id: str
    scenario_type: ScenarioType
    target_parameter_key: str
    proposed_value: Any
    unit: str
    rationale: str
    evidence_refs: List[str] = field(default_factory=list)
    has_identified_causal_model: bool = False
    causal_identification_assumptions: List[str] = field(default_factory=list)


@dataclass
class ScenarioEvaluationResult:
    child_snapshot_id: str
    base_snapshot_id: str
    scenario_type: ScenarioType
    target_key: str
    original_value: Any
    patched_value: Any
    
    # State flags
    causal_claim_rejected: bool
    label: str
    rejection_explanation: Optional[str]
    held_constant: List[str]
    downstream_mechanisms_responded: List[str]
    
    # Recalculated economics
    base_economics: Dict[str, Any]
    child_economics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "child_snapshot_id": self.child_snapshot_id,
            "base_snapshot_id": self.base_snapshot_id,
            "scenario_type": self.scenario_type.value,
            "target_key": self.target_key,
            "original_value": str(self.original_value),
            "patched_value": str(self.patched_value),
            "causal_claim_rejected": self.causal_claim_rejected,
            "label": self.label,
            "rejection_explanation": self.rejection_explanation,
            "held_constant": self.held_constant,
            "downstream_mechanisms_responded": self.downstream_mechanisms_responded,
            "base_economics": self.base_economics,
            "child_economics": self.child_economics,
        }


class ScenarioEngine:
    """Manages immutable snapshots, sensitivity patches, and causal counterfactual validation."""

    def apply_patch(
        self,
        base_snapshot: Dict[str, Any],
        patch: ScenarioPatchModel,
        strict_causal: bool = False,
    ) -> ScenarioEvaluationResult:
        base_id = patch.base_snapshot_id
        target = patch.target_parameter_key

        if target not in base_snapshot:
            raise KeyError(f"Target parameter '{target}' does not exist in base snapshot {base_id}")

        orig_val = base_snapshot[target]
        child_id = f"snap-{uuid.uuid4().hex[:12]}"

        # Deep clone snapshot parameters to ensure base immutability
        child_params = copy.deepcopy(base_snapshot)
        child_params[target] = patch.proposed_value

        # Causal identification check (SRS-036, AT-028)
        causal_rejected = False
        rejection_expl = None
        effective_label = patch.scenario_type.value

        if patch.scenario_type == ScenarioType.CAUSAL_COUNTERFACTUAL:
            if not patch.has_identified_causal_model:
                causal_rejected = True
                rejection_expl = (
                    f"Causal claim rejected: no identified causal DAG or exogenous instrument exists for '{target}'. "
                    f"Downstream changes are labeled SENSITIVITY rather than causal uplift (SRS-036, AT-028)."
                )
                effective_label = ScenarioType.SENSITIVITY.value
                if strict_causal:
                    raise CausalIdentificationError(rejection_expl)

        # Helper to compute unit economics on snapshot
        def _compute_econ(params: Dict[str, Any]) -> Dict[str, Any]:
            p = Decimal(str(params.get("price", 699.0)))
            c = Decimal(str(params.get("cogs", 315.0)))
            f = Decimal(str(params.get("fulfillment", 60.0)))
            fee_r = Decimal(str(params.get("payment_fee_rate", 0.03)))
            cac = Decimal(str(params.get("acquisition_cost", 140.0)))
            fixed = Decimal(str(params.get("fixed_costs", 120000.0)))
            u = int(params.get("units", 900))
            curr = str(params.get("currency", "INR"))

            econ = UnitEconomics(
                price=p,
                cogs=c,
                fulfillment=f,
                payment_fee_rate=fee_r,
                acquisition_cost=cac,
                fixed_costs=fixed,
                units=u,
                currency=curr,
            )
            return econ.summary()

        base_econ = _compute_econ(base_snapshot)
        child_econ = _compute_econ(child_params)

        # Determine held constant vs responded
        held_constant = [k for k in base_snapshot if k != target]
        responded = ["contribution_per_unit", "profit", "break_even_units"]

        return ScenarioEvaluationResult(
            child_snapshot_id=child_id,
            base_snapshot_id=base_id,
            scenario_type=patch.scenario_type,
            target_key=target,
            original_value=orig_val,
            patched_value=patch.proposed_value,
            causal_claim_rejected=causal_rejected,
            label=effective_label,
            rejection_explanation=rejection_expl,
            held_constant=held_constant,
            downstream_mechanisms_responded=responded,
            base_economics=base_econ,
            child_economics=child_econ,
        )
