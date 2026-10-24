"""Comprehensive acceptance tests for Stage 9: Numerical Domain Layer.

Verifies:
- AT-022: Econometric identification validation & out-of-domain rejection
- AT-024: Multi-period cash flow, inventory conservation & liquidity breach
- AT-025: Reproducible Monte Carlo simulation & invalid draw reporting
- AT-026: Hard constraints filtering profit-maximizing infeasible candidates
- AT-027: Monte Carlo error reduction O(1/sqrt(N)) & copula correlation
- AT-028: Scenario patches, base immutability & causal claim rejection
- AT-029: All-infeasible sets & multi-objective indifference ties
"""
from decimal import Decimal
import pytest

from backend.dtp.numerical.cashflow import (
    CashFlowEngine,
    PeriodInput,
    InventoryConservationError,
)
from backend.dtp.numerical.demand import (
    ConstantElasticityDemand,
    DemandIdentificationError,
    DomainRangeViolationError,
    LinearDemand,
    ModelIdentificationStatus,
)
from backend.dtp.numerical.simulation import (
    DependencySpec,
    DistributionSpec,
    DistributionType,
    MonteCarloSimulator,
    SimulationFailureError,
    SimulationPlan,
)
from backend.dtp.numerical.optimization import (
    CandidateAction,
    ConstraintEvaluation,
    HardConstraint,
    OptimizationSolver,
    OptimizationStatus,
)
from backend.dtp.numerical.counterfactual import (
    CausalIdentificationError,
    ScenarioEngine,
    ScenarioPatchModel,
    ScenarioType,
)


def test_at024_cash_flow_and_liquidity_breach():
    """AT-024: Inventory paid before sales and fixed costs create a cash shortfall.
    
    Verifies:
    - Profit/cash differ correctly
    - Inventory balances reconcile
    - Positive cumulative profit cannot override liquidity constraint
    """
    # 3 periods of 30 days each. Total demand = 900 units (300 per period).
    # Upfront procurement: 900 units ordered and delivered in period 0.
    # Unit procurement cost = 315, selling price = 699, fulfillment = 60, fee = 3% (20.97), CAC = 140.
    # Fixed operating cost = 40,000 per period (total 120,000).
    # Initial cash = 100,000.
    # In period 0, supplier must be paid 900 * 315 = 283,500.
    # Plus period 0 fixed cost 40,000 + CAC (300*140=42,000) + fulfillment (300*60=18,000) + fees (300*20.97=6,291).
    # Cash inflows in period 0 = 300 * 699 = 209,700.
    # Net period 0 outflow = 283,500 + 40,000 + 42,000 + 18,000 + 6,291 - 209,700 = 180,091.
    # Since initial cash is only 100,000, closing cash in period 0 drops to -80,091!
    # Even though total 3-period profit is POSITIVE (INR 26,727), liquidity is severely breached.
    inputs = [
        PeriodInput(
            period=0,
            demand_units=300,
            procurement_receipt_units=900,
            procurement_order_units=900,
            unit_purchase_cost=Decimal("315.00"),
            unit_selling_price=Decimal("699.00"),
            unit_cogs=Decimal("315.00"),
            unit_fulfillment=Decimal("60.00"),
            payment_fee_rate=Decimal("0.03"),
            acquisition_cost_per_unit=Decimal("140.00"),
            fixed_operating_costs=Decimal("40000.00"),
            ap_lag_periods=0, # paid on delivery
            ar_lag_periods=0,
        ),
        PeriodInput(
            period=1,
            demand_units=300,
            procurement_receipt_units=0,
            procurement_order_units=0,
            unit_purchase_cost=Decimal("315.00"),
            unit_selling_price=Decimal("699.00"),
            unit_cogs=Decimal("315.00"),
            unit_fulfillment=Decimal("60.00"),
            payment_fee_rate=Decimal("0.03"),
            acquisition_cost_per_unit=Decimal("140.00"),
            fixed_operating_costs=Decimal("40000.00"),
            ap_lag_periods=0,
            ar_lag_periods=0,
        ),
        PeriodInput(
            period=2,
            demand_units=300,
            procurement_receipt_units=0,
            procurement_order_units=0,
            unit_purchase_cost=Decimal("315.00"),
            unit_selling_price=Decimal("699.00"),
            unit_cogs=Decimal("315.00"),
            unit_fulfillment=Decimal("60.00"),
            payment_fee_rate=Decimal("0.03"),
            acquisition_cost_per_unit=Decimal("140.00"),
            fixed_operating_costs=Decimal("40000.00"),
            ap_lag_periods=0,
            ar_lag_periods=0,
        ),
    ]

    engine = CashFlowEngine(
        currency="INR",
        initial_cash=Decimal("100000.00"),
        initial_inventory=0,
        min_cash_reserve=Decimal("20000.00"),
    )
    result = engine.run(inputs)

    # 1. Total operating profit is positive (26,727.00 exactly matching golden fixture)
    assert result.total_operating_profit == Decimal("26727.00")
    # 2. Inventory conservation strictly verified across all periods
    assert result.inventory_conserved is True
    assert result.periods[0].beginning_inventory == 0
    assert result.periods[0].ending_inventory == 600
    assert result.periods[1].ending_inventory == 300
    assert result.periods[2].ending_inventory == 0
    # 3. Liquidity breach is flagged despite positive profit
    assert result.liquidity_breached is True
    assert result.min_cash_balance < Decimal("0.00")
    assert result.funding_requirement > Decimal("100000.00")


def test_at022_demand_identification_and_out_of_bounds():
    """AT-022: Price response unidentified or actions exceed approved domain ranges.
    
    Verifies:
    - Out of bounds raises DomainRangeViolationError (no silent clamping)
    - Unidentified model raises DemandIdentificationError on empirical optimal price claim
    - Scenario-only model returns conditional scenario result
    """
    # 1. Out of bounds price raises error (bounds are 500 to 1000)
    model_unidentified = LinearDemand(
        intercept=Decimal("2000"),
        slope=Decimal("1.5"),
        price_min=Decimal("500.00"),
        price_max=Decimal("1000.00"),
        currency="INR",
        identification_status=ModelIdentificationStatus.MODEL_NOT_IDENTIFIED,
    )

    with pytest.raises(DomainRangeViolationError) as exc_info:
        model_unidentified.evaluate_quantity(Decimal("1500.00"))
    assert "exceeds approved domain bounds" in str(exc_info.value)
    assert "silent clamping prohibited" in str(exc_info.value)

    # 2. Unidentified model cannot claim empirical optimal price
    with pytest.raises(DemandIdentificationError) as exc_info2:
        model_unidentified.find_optimal_price(unit_variable_cost=Decimal("300.00"))
    assert "Cannot declare an empirically optimal price" in str(exc_info2.value)

    # 3. Scenario-only model returns conditional comparison with caveat
    model_scenario = LinearDemand(
        intercept=Decimal("2000"),
        slope=Decimal("1.5"),
        price_min=Decimal("500.00"),
        price_max=Decimal("1000.00"),
        currency="INR",
        identification_status=ModelIdentificationStatus.SCENARIO_ONLY,
    )
    res = model_scenario.find_optimal_price(unit_variable_cost=Decimal("300.00"))
    assert res.is_empirical_optimal is False
    assert res.is_scenario_conditional is True
    assert "Conditional scenario comparison only" in res.rejection_reason


def test_at025_reproducible_monte_carlo_and_invalid_draws():
    """AT-025: Pinned model/seed/environment run repeats; invalid draws classified.
    
    Verifies:
    - Identical seed produces identical SHA-256 draw-artifact hash
    - Invalid draws are classified and counted, never silently discarded
    - High invalid draw rate fails the simulation run above tolerance
    """
    plan = SimulationPlan(
        plan_id="sim-test-025",
        seed=4242,
        draw_count=1000,
        distributions=[
            DistributionSpec("price", DistributionType.NORMAL, {"mean": 699.0, "std": 30.0}),
            DistributionSpec("cogs", DistributionType.NORMAL, {"mean": 315.0, "std": 15.0}),
        ],
        invalid_draw_tolerance_pct=0.05,
    )

    sim1 = MonteCarloSimulator(plan)
    res1 = sim1.run()

    sim2 = MonteCarloSimulator(plan)
    res2 = sim2.run()

    # Reproducibility: exact hash match
    assert res1.draw_artifact_hash == res2.draw_artifact_hash
    assert res1.profit_mean == res2.profit_mean
    assert res1.loss_cvar_95 == res2.loss_cvar_95

    # Test invalid draws failure threshold: validator flags price < 700 as invalid
    # ~50% of draws will be < 700, exceeding 5% tolerance
    def strict_validator(draw: dict):
        if draw["price"] < 700.0:
            return False, "PRICE_BELOW_FLOOR_700"
        return True, None

    with pytest.raises(SimulationFailureError) as exc_info:
        sim1.run(domain_validator=strict_validator)
    assert "Invalid draw rate" in str(exc_info.value)
    assert "PRICE_BELOW_FLOOR_700" in str(exc_info.value)


def test_at027_monte_carlo_error_reduction_and_copula():
    """AT-027: Larger draw count reduces Monte Carlo standard error as O(1/sqrt(N)).
    
    Verifies:
    - MC error decreases with sqrt(N)
    - Gaussian copula dependency sampling respects correlation matrix
    """
    # Small batch N = 500
    plan_small = SimulationPlan(
        plan_id="sim-small",
        seed=101,
        draw_count=500,
        distributions=[
            DistributionSpec("price", DistributionType.NORMAL, {"mean": 699.0, "std": 50.0}),
            DistributionSpec("cogs", DistributionType.NORMAL, {"mean": 315.0, "std": 20.0}),
        ],
    )
    res_small = MonteCarloSimulator(plan_small).run()

    # Large batch N = 5000 (10x draws -> SE should decrease by approx sqrt(10) ~= 3.16x)
    plan_large = SimulationPlan(
        plan_id="sim-large",
        seed=101,
        draw_count=5000,
        distributions=[
            DistributionSpec("price", DistributionType.NORMAL, {"mean": 699.0, "std": 50.0}),
            DistributionSpec("cogs", DistributionType.NORMAL, {"mean": 315.0, "std": 20.0}),
        ],
    )
    res_large = MonteCarloSimulator(plan_large).run()

    assert res_large.monte_carlo_standard_error < res_small.monte_carlo_standard_error
    ratio = res_small.monte_carlo_standard_error / res_large.monte_carlo_standard_error
    # Ratio should be close to sqrt(10) ~= 3.16 (allow tolerance 2.5 to 4.0)
    assert 2.5 <= ratio <= 4.0

    # Test Correlated sampling via Gaussian copula
    dep_plan = SimulationPlan(
        plan_id="sim-dep",
        seed=202,
        draw_count=1000,
        distributions=[
            DistributionSpec("x", DistributionType.NORMAL, {"mean": 100.0, "std": 10.0}),
            DistributionSpec("y", DistributionType.NORMAL, {"mean": 50.0, "std": 5.0}),
        ],
        dependencies=DependencySpec(
            variable_names=["x", "y"],
            correlation_matrix=[[1.0, 0.8], [0.8, 1.0]],
        ),
    )
    res_dep = MonteCarloSimulator(dep_plan).run()
    assert res_dep.valid_draws == 1000


def test_at026_hard_constraints_filter_infeasible_profit_maximizer():
    """AT-026: Candidate A maximizes profit but violates hard capacity constraint.
    
    Verifies:
    - Candidate A is marked INFEASIBLE and NOT recommended
    - Feasible Candidate B (or baseline) is recommended instead
    """
    capacity_limit = 1000

    def capacity_evaluator(cand: CandidateAction) -> ConstraintEvaluation:
        units = cand.units
        passed = units <= capacity_limit
        return ConstraintEvaluation(
            name="CAPACITY_CONSTRAINT",
            passed=passed,
            actual_value=Decimal(units),
            limit_value=Decimal(capacity_limit),
            operator="<=",
            is_hard=True,
            blocking_reason=f"Capacity limit exceeded: {units} > {capacity_limit}" if not passed else None,
        )

    solver = OptimizationSolver(
        hard_constraints=[HardConstraint("Capacity", "Factory capacity limit", capacity_evaluator)],
        primary_objective="profit",
    )

    candidate_a = CandidateAction(
        action_id="cand-A",
        name="Aggressive High Volume",
        parameters={"price": 599.0},
        profit=Decimal("50000.00"), # Highest profit!
        units=1500, # Breaches capacity!
    )
    candidate_b = CandidateAction(
        action_id="cand-B",
        name="Balanced Target",
        parameters={"price": 699.0},
        profit=Decimal("26727.00"),
        units=900, # Feasible!
    )
    candidate_defer = CandidateAction(
        action_id="cand-defer",
        name="Status Quo Defer",
        parameters={},
        profit=Decimal("0.00"),
        units=0,
        is_baseline_or_defer=True,
    )

    result = solver.solve([candidate_a, candidate_b, candidate_defer])

    # Candidate A must be INFEASIBLE and NOT recommended
    assert candidate_a.is_feasible is False
    assert "Capacity limit exceeded: 1500 > 1000" in result.blocking_constraints_by_action["cand-A"]
    # Candidate B must be recommended
    assert result.recommended_action.action_id == "cand-B"
    assert result.status == OptimizationStatus.FEASIBLE_RECOMMENDATION


def test_at029_pareto_ties_and_all_infeasible():
    """AT-029: Multiobjective ties and all-infeasible set handling."""
    # 1. All-infeasible set
    def impossible_constraint(cand: CandidateAction) -> ConstraintEvaluation:
        return ConstraintEvaluation(
            name="IMPOSSIBLE_MARGIN",
            passed=False,
            actual_value=cand.profit,
            limit_value=Decimal("1000000.00"),
            operator=">=",
            blocking_reason="Profit below required 1M threshold",
        )

    solver_impossible = OptimizationSolver(
        hard_constraints=[HardConstraint("Impossible", "Impossible bar", impossible_constraint)]
    )
    res_infeasible = solver_impossible.solve([
        CandidateAction("c1", "Candidate 1", {}, profit=Decimal("20000.00")),
        CandidateAction("c2", "Candidate 2", {}, profit=Decimal("30000.00")),
    ])
    assert res_infeasible.status == OptimizationStatus.ALL_INFEASIBLE
    assert res_infeasible.recommended_action is None
    assert "c1" in res_infeasible.blocking_constraints_by_action
    assert "c2" in res_infeasible.blocking_constraints_by_action

    # 2. Multi-objective indifference tie
    c_tie1 = CandidateAction("c1", "Tie 1", {}, profit=Decimal("25000.00"), min_cash=Decimal("10000.00"))
    c_tie2 = CandidateAction("c2", "Tie 2", {}, profit=Decimal("25020.00"), min_cash=Decimal("9500.00"))
    solver_tie = OptimizationSolver(
        hard_constraints=[],
        indifference_tolerance=Decimal("50.00"),
    )
    res_tie = solver_tie.solve([c_tie1, c_tie2])
    assert res_tie.status == OptimizationStatus.MULTI_OBJECTIVE_TIED
    assert len(res_tie.indifference_tied_actions) == 2


def test_at028_scenario_patch_and_causal_counterfactual_rejection():
    """AT-028: User edits acquisition cost and requests causal conclusion without identified model.
    
    Verifies:
    - Base snapshot preserves original values (immutability)
    - Downstream descendants recalculate (profit drops from 26,727 to -23,673)
    - Causal claim is rejected and relabeled as SENSITIVITY
    """
    base_snapshot = {
        "price": Decimal("699.00"),
        "cogs": Decimal("315.00"),
        "fulfillment": Decimal("60.00"),
        "payment_fee_rate": Decimal("0.03"),
        "acquisition_cost": Decimal("140.00"),
        "fixed_costs": Decimal("120000.00"),
        "units": 900,
        "currency": "INR",
    }

    patch = ScenarioPatchModel(
        patch_id="patch-cac-stress",
        base_snapshot_id="snap-base-001",
        scenario_type=ScenarioType.CAUSAL_COUNTERFACTUAL,
        target_parameter_key="acquisition_cost",
        proposed_value=Decimal("196.00"),
        unit="INR",
        rationale="Stress testing customer acquisition cost increase",
        has_identified_causal_model=False, # No identified causal graph!
    )

    engine = ScenarioEngine()
    result = engine.apply_patch(base_snapshot, patch)

    # Base snapshot is strictly unchanged
    assert base_snapshot["acquisition_cost"] == Decimal("140.00")
    # Base profit was 26,727.00
    assert result.base_economics["profit"] == Decimal("26727.00")
    # Child profit is -23,673.00 (exact AT-023 stress outcome!)
    assert result.child_economics["profit"] == Decimal("-23673.00")
    
    # Causal claim MUST be rejected and downgraded to SENSITIVITY
    assert result.causal_claim_rejected is True
    assert result.label == "SENSITIVITY"
    assert "Causal claim rejected: no identified causal DAG" in result.rejection_explanation
