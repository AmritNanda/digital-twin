"""Numerical domain layer for Company and Market Twin (SRS-030 - SRS-037).

Provides deterministic and reproducible numerical engines:
- Multi-period cash flow and working capital dynamics (SRS-032, SRS-033, AT-024)
- Price elasticity and demand identification validation (SRS-031, SRS-034, AT-022)
- Reproducible Monte Carlo simulation with copula sampling (SRS-035, AT-025, AT-027)
- Pareto multi-objective optimization with hard constraints (SRS-037, AT-026, AT-029)
- Scenario patches and counterfactual validation (SRS-036, AT-028)
"""

from backend.dtp.numerical.cashflow import (
    CashFlowEngine,
    CashFlowPeriod,
    CashFlowResult,
    InventoryConservationError,
    LiquidityBreachError,
)
from backend.dtp.numerical.demand import (
    ConstantElasticityDemand,
    DemandIdentificationError,
    DemandIdentificationValidator,
    DemandModel,
    LinearDemand,
    LogitChoiceDemand,
    ModelIdentificationStatus,
)
from backend.dtp.numerical.simulation import (
    DistributionSpec,
    MonteCarloSimulator,
    SimulationFailureError,
    SimulationPlan,
    SimulationResultSummary,
)
from backend.dtp.numerical.optimization import (
    CandidateAction,
    ConstraintEvaluation,
    HardConstraint,
    OptimizationResult,
    OptimizationSolver,
)
from backend.dtp.numerical.counterfactual import (
    CausalIdentificationError,
    ScenarioEngine,
    ScenarioPatchModel,
    ScenarioType,
)

__all__ = [
    "CashFlowEngine",
    "CashFlowPeriod",
    "CashFlowResult",
    "InventoryConservationError",
    "LiquidityBreachError",
    "ConstantElasticityDemand",
    "DemandIdentificationError",
    "DemandIdentificationValidator",
    "DemandModel",
    "LinearDemand",
    "LogitChoiceDemand",
    "ModelIdentificationStatus",
    "DistributionSpec",
    "MonteCarloSimulator",
    "SimulationFailureError",
    "SimulationPlan",
    "SimulationResultSummary",
    "CandidateAction",
    "ConstraintEvaluation",
    "HardConstraint",
    "OptimizationResult",
    "OptimizationSolver",
    "CausalIdentificationError",
    "ScenarioEngine",
    "ScenarioPatchModel",
    "ScenarioType",
]
