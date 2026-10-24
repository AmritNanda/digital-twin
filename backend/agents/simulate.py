"""
Simulation Agent — Node 5 in the LangGraph.

Responsibilities:
- Run a proper Monte Carlo simulation for each hypothesis
- Use evidence-grounded parameters (from the twin) with uncertainty distributions
- Compute profit distributions, P(success), sensitivities
- NOT use LLM for calculations — this is deterministic numerical work
- Update hypothesis confidence based on simulation results
"""
from __future__ import annotations
import logging
import math
import numpy as np
from numpy.random import default_rng
from twin import DigitalTwin, SimulationResult, to_float

logger = logging.getLogger(__name__)

N_DRAWS = 5000   # Monte Carlo samples per hypothesis
SEED_BASE = 42   # Reproducible (per-hypothesis offset)


def _get_param(twin: DigitalTwin, key: str, default: float) -> tuple[float, float]:
    """
    Return (mean, std_dev) for a financial parameter.
    If the parameter is KNOWN, std is small. If INFERRED/ASSUMED, wider uncertainty.
    """
    attrs = {}
    if twin.products:
        attrs = twin.products[0].attributes

    # Also check segments
    val = attrs.get(key)
    if val is None:
        # Try competitors for price reference
        if key == "competitor_price_inr" and twin.competitors:
            val = twin.competitors[0].attributes.get("price_inr")

    val = to_float(val, default)
    if key == "elasticity" and val > 0:
        val = -val   # demand falls as price rises; LLMs often report magnitude only

    # Uncertainty: wider if estimated, narrow if stated
    uncertainty_factor = 0.2   # 20% std dev as default
    std = abs(val) * uncertainty_factor
    return float(val), float(std)


def _simulate_hypothesis(
    twin: DigitalTwin,
    h_id: str,
    price: float,
    channel: str,
    rng: np.random.Generator,
) -> SimulationResult:
    """
    Monte Carlo profit simulation for one hypothesis.

    Revenue model:
      demand ~ Normal(mean_demand, sigma_demand)
      mean_demand = base_demand * (price / ref_price) ^ elasticity
      revenue = demand * price
      variable_cost = demand * unit_cost
      cac_total = demand * conversion_rate * cac
      profit = revenue - variable_cost - fixed_cost - cac_total

    All parameters drawn from distributions reflecting evidence quality.
    """
    # Pull parameters from twin
    base_demand_m, base_demand_s = _get_param(twin, "base_demand", 1000.0)
    elasticity_m, elasticity_s = _get_param(twin, "elasticity", -1.2)
    elasticity_s = max(elasticity_s, 0.15)   # minimum uncertainty on elasticity
    unit_cost_m, unit_cost_s = _get_param(twin, "unit_cost_inr", 200.0)
    fixed_cost_m, fixed_cost_s = _get_param(twin, "fixed_cost_inr", 50000.0)
    cac_m, cac_s = _get_param(twin, "cac_inr", 300.0)
    cac_s = max(cac_s, 50.0)   # CAC has real uncertainty

    ref_price = 500.0   # Reference price for elasticity calculation

    # Channel-specific adjustments
    channel_lower = (channel or "").lower()
    if "retail" in channel_lower:
        margin_adjustment = 0.7   # retailer takes ~30%
        cac_adjustment = 0.5      # lower marketing CAC
    elif "premium" in channel_lower:
        margin_adjustment = 1.0
        cac_adjustment = 1.5      # premium CAC higher
    elif "pilot" in channel_lower:
        margin_adjustment = 1.0
        cac_adjustment = 0.3
        base_demand_m *= 0.15    # pilot = small scale
    else:  # d2c / online
        margin_adjustment = 1.0
        cac_adjustment = 1.0

    # Monte Carlo draws
    profits = np.zeros(N_DRAWS)
    demands = np.zeros(N_DRAWS)

    for i in range(N_DRAWS):
        # Draw from parameter distributions
        elasticity = rng.normal(elasticity_m, elasticity_s)
        base_demand = max(0, rng.normal(base_demand_m, base_demand_s))
        unit_cost = max(0, rng.normal(unit_cost_m, unit_cost_s))
        fixed_cost = max(0, rng.normal(fixed_cost_m, fixed_cost_s))
        cac = max(0, rng.normal(cac_m * cac_adjustment, cac_s))

        # Demand model: log-linear price response
        demand = base_demand * math.exp(elasticity * math.log(price / ref_price))
        demand = max(0, demand)

        # Add demand noise (market uncertainty)
        demand = max(0, demand * (1 + rng.normal(0, 0.15)))

        # Revenue and costs
        effective_price = price * margin_adjustment
        revenue = demand * effective_price
        var_cost = demand * unit_cost
        cac_total = demand * 0.05 * cac    # assume 5% of sales need marketing-acquired customers
        profit = revenue - var_cost - fixed_cost - cac_total

        profits[i] = profit
        demands[i] = demand

    avg_profit = float(np.mean(profits))
    prob_positive = float(np.mean(profits > 0))
    p10 = float(np.percentile(profits, 10))
    p50 = float(np.percentile(profits, 50))
    p90 = float(np.percentile(profits, 90))
    avg_demand = float(np.mean(demands))

    return SimulationResult(
        hypothesis_id=h_id,
        price=price,
        channel=channel or "unknown",
        avg_profit=avg_profit,
        prob_positive=prob_positive,
        p10_profit=p10,
        p50_profit=p50,
        p90_profit=p90,
        avg_monthly_demand=avg_demand,
        assumptions_used={
            "base_demand_mean": base_demand_m,
            "elasticity_mean": elasticity_m,
            "unit_cost_mean": unit_cost_m,
            "fixed_cost_mean": fixed_cost_m,
            "cac_mean": cac_m,
            "n_draws": N_DRAWS,
        },
    )


def sensitivity_grid(twin: DigitalTwin) -> list[dict]:
    """Compare option rankings across approved elasticity and CAC scenarios."""
    if not twin.current_hypotheses():
        return []
    elasticity = _get_param(twin, "elasticity", -1.2)[0]
    cac = _get_param(twin, "cac_inr", 300.0)[0]
    points = []
    for elasticity_factor in (0.75, 1.0, 1.25):
        for cac_factor in (0.7, 1.0, 1.3):
            scenario = twin.model_copy(deep=True)
            scenario.primary_product().attributes.update({
                "elasticity": elasticity * elasticity_factor,
                "cac_inr": cac * cac_factor,
            })
            sims = []
            for idx, hyp in enumerate(scenario.current_hypotheses()):
                price = to_float(hyp.price, 699.0) or 699.0
                sims.append(_simulate_hypothesis(scenario, hyp.id, price,
                                                  hyp.channel or "d2c", default_rng(SEED_BASE + idx)))
            leader = max(sims, key=lambda item: item.avg_profit)
            points.append({"elasticity": elasticity * elasticity_factor,
                           "cac_inr": cac * cac_factor,
                           "leader_hypothesis_id": leader.hypothesis_id,
                           "leader_avg_profit": leader.avg_profit,
                           "options": {sim.hypothesis_id: sim.avg_profit for sim in sims}})
    return points


async def simulation_node(state: dict) -> dict:
    """LangGraph node: run Monte Carlo simulation for all active hypotheses."""
    twin_data = state.get("twin", {})
    twin = DigitalTwin(**twin_data) if twin_data else None

    if not twin or not twin.current_hypotheses():
        return {"events": [{
            "type": "agent_skip",
            "agent": "Simulation Agent",
            "message": "No hypotheses to simulate",
        }]}

    events = [{
        "type": "agent_start",
        "agent": "Simulation Agent",
        "message": f"Running Monte Carlo simulation ({N_DRAWS:,} draws) for {len(twin.current_hypotheses())} hypotheses...",
        "iteration": state.get("iteration", 0),
    }]

    rng = default_rng(SEED_BASE + state.get("iteration", 0))
    sim_results = []

    for idx, hyp in enumerate(twin.current_hypotheses()):
        price = to_float(hyp.price, 0.0) or 0.0
        if price <= 0:
            price = 699.0
        channel = hyp.channel or "d2c"

        sim = _simulate_hypothesis(twin, hyp.id, price, channel, rng)
        twin.add_simulation(sim)
        sim_results.append(sim)

        # Update hypothesis confidence based on simulation
        hyp.confidence = round(sim.prob_positive * 0.7 + hyp.confidence * 0.3, 3)
        hyp.updated_at = sim.created_at
        events.append({
            "type": "simulation_result",
            "agent": "Simulation Agent",
            "hypothesis_id": hyp.id,
            "hypothesis_title": hyp.title,
            "price": price,
            "channel": channel,
            "avg_profit": round(sim.avg_profit),
            "prob_positive": round(sim.prob_positive * 100, 1),
            "p10": round(sim.p10_profit),
            "p50": round(sim.p50_profit),
            "p90": round(sim.p90_profit),
            "avg_demand": round(sim.avg_monthly_demand),
            "confidence": hyp.confidence,
            "message": (
                f"{hyp.title}: avg profit ₹{sim.avg_profit:,.0f}, "
                f"{sim.prob_positive*100:.0f}% chance of profitability"
            ),
        })

    # Rank hypotheses by expected profit
    ranked = sorted(
        [(s, next(h for h in twin.hypotheses if h.id == s.hypothesis_id)) for s in sim_results],
        key=lambda x: x[0].avg_profit,
        reverse=True,
    )

    if ranked:
        best_sim, best_hyp = ranked[0]
        events.append({
            "type": "agent_complete",
            "agent": "Simulation Agent",
            "message": (
                f"Leading hypothesis: '{best_hyp.title}' @ ₹{best_sim.price:.0f} "
                f"(avg profit ₹{best_sim.avg_profit:,.0f}, "
                f"{best_sim.prob_positive*100:.0f}% profitable)"
            ),
            "leading_hypothesis": best_hyp.title,
        })

    return {
        "twin": twin.model_dump(),
        "events": events,
    }
