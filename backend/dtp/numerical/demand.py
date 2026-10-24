"""Price elasticity, choice demand models, and econometric identification validation (SRS-031, SRS-034, AT-022).

Enforces strict econometric identification guards:
- Out-of-domain price actions raise DomainRangeViolationError (no silent clamping)
- Unidentified models return MODEL_NOT_IDENTIFIED and block empirical optimal price claims
- Hypothetical assumptions return SCENARIO_ONLY conditional comparisons
- Full conservation of choice probabilities in multinomial logit models
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import List, Optional, Tuple, Dict, Any

CENT = Decimal("0.01")


class ModelIdentificationStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    SCENARIO_ONLY = "SCENARIO_ONLY"
    MODEL_NOT_IDENTIFIED = "MODEL_NOT_IDENTIFIED"


class DomainRangeViolationError(ValueError):
    """Raised when price action exceeds approved domain bounds (AT-022: no silent clamping)."""
    pass


class DemandIdentificationError(RuntimeError):
    """Raised when an empirical optimal price claim is attempted on an unidentified model (SRS-034, AT-022)."""
    pass


@dataclass
class DemandIdentificationValidator:
    """Validates whether empirical demand data satisfies identification standards."""
    
    has_price_variation: bool
    sample_size: int
    temporal_holdout_validated: bool
    instrument_or_exogenous_variation: bool
    missingness_controlled: bool
    min_price_points: int = 3
    min_observations: int = 50

    def validate(self) -> ModelIdentificationStatus:
        if not self.has_price_variation:
            return ModelIdentificationStatus.MODEL_NOT_IDENTIFIED
        if self.sample_size < self.min_observations:
            return ModelIdentificationStatus.MODEL_NOT_IDENTIFIED
        if not self.temporal_holdout_validated:
            return ModelIdentificationStatus.SCENARIO_ONLY
        if not self.instrument_or_exogenous_variation:
            return ModelIdentificationStatus.SCENARIO_ONLY
        return ModelIdentificationStatus.IDENTIFIED


@dataclass
class OptimalPriceResult:
    status: ModelIdentificationStatus
    optimal_price: Optional[Decimal]
    expected_quantity: Optional[int]
    expected_contribution: Optional[Decimal]
    is_empirical_optimal: bool
    is_scenario_conditional: bool
    rejection_reason: Optional[str] = None
    evaluated_candidates: List[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "optimal_price": str(self.optimal_price.quantize(CENT, ROUND_HALF_UP)) if self.optimal_price is not None else None,
            "expected_quantity": self.expected_quantity,
            "expected_contribution": str(self.expected_contribution.quantize(CENT, ROUND_HALF_UP)) if self.expected_contribution is not None else None,
            "is_empirical_optimal": self.is_empirical_optimal,
            "is_scenario_conditional": self.is_scenario_conditional,
            "rejection_reason": self.rejection_reason,
            "evaluated_count": len(self.evaluated_candidates or []),
        }


class DemandModel(ABC):
    """Abstract base class for domain demand models."""
    
    def __init__(
        self,
        price_min: Decimal,
        price_max: Decimal,
        currency: str,
        identification_status: ModelIdentificationStatus = ModelIdentificationStatus.SCENARIO_ONLY,
    ):
        if price_min <= 0:
            raise ValueError(f"price_min must be positive, got {price_min}")
        if price_max < price_min:
            raise ValueError(f"price_max {price_max} cannot be less than price_min {price_min}")
        self.price_min = Decimal(price_min)
        self.price_max = Decimal(price_max)
        self.currency = currency
        self.identification_status = identification_status

    def check_bounds(self, price: Decimal) -> None:
        p = Decimal(price)
        if p < self.price_min or p > self.price_max:
            raise DomainRangeViolationError(
                f"Proposed price {p} exceeds approved domain bounds [{self.price_min}, {self.price_max}] in {self.currency} (SRS-034, AT-022: silent clamping prohibited)"
            )

    @abstractmethod
    def evaluate_quantity(self, price: Decimal) -> int:
        pass

    def evaluate_candidates(self, prices: List[Decimal], unit_cost: Decimal) -> List[Dict[str, Any]]:
        results = []
        for p in prices:
            self.check_bounds(p)
            q = self.evaluate_quantity(p)
            unit_margin = p - unit_cost
            tot_margin = unit_margin * Decimal(q)
            results.append({
                "price": str(p),
                "quantity": q,
                "unit_margin": str(unit_margin),
                "total_margin": str(tot_margin),
            })
        return results

    def find_optimal_price(
        self,
        unit_variable_cost: Decimal,
        grid_step: Decimal = Decimal("1.00"),
    ) -> OptimalPriceResult:
        """Finds profit-maximizing price under approved bounds and identification policy (AT-022)."""
        # Strict guard: unidentified models CANNOT declare an optimal price
        if self.identification_status == ModelIdentificationStatus.MODEL_NOT_IDENTIFIED:
            raise DemandIdentificationError(
                "Price response model is not identified. Cannot declare an empirically optimal price (SRS-034, AT-022). Must return MODEL_NOT_IDENTIFIED or conditional scenario comparison."
            )

        candidates: List[Dict[str, Any]] = []
        current_p = self.price_min
        best_p: Optional[Decimal] = None
        best_profit: Decimal = Decimal("-Infinity")
        best_q: int = 0

        while current_p <= self.price_max:
            q = self.evaluate_quantity(current_p)
            margin_per_unit = current_p - Decimal(unit_variable_cost)
            profit = margin_per_unit * Decimal(q)
            
            candidates.append({
                "price": current_p,
                "quantity": q,
                "profit": profit,
            })
            
            if profit > best_profit:
                best_profit = profit
                best_p = current_p
                best_q = q
            
            current_p += grid_step

        is_empirical = (self.identification_status == ModelIdentificationStatus.IDENTIFIED)
        is_conditional = (self.identification_status == ModelIdentificationStatus.SCENARIO_ONLY)

        return OptimalPriceResult(
            status=self.identification_status,
            optimal_price=best_p,
            expected_quantity=best_q,
            expected_contribution=best_profit,
            is_empirical_optimal=is_empirical,
            is_scenario_conditional=is_conditional,
            rejection_reason=None if is_empirical else "Conditional scenario comparison only: empirical price elasticity not identified",
            evaluated_candidates=[
                {"price": str(c["price"]), "quantity": c["quantity"], "profit": str(c["profit"])}
                for c in candidates
            ],
        )


class ConstantElasticityDemand(DemandModel):
    """Constant elasticity model: Q(P) = Q0 * (P / P0)^epsilon."""

    def __init__(
        self,
        base_price: Decimal,
        base_quantity: int,
        elasticity: Decimal,
        price_min: Decimal,
        price_max: Decimal,
        currency: str,
        identification_status: ModelIdentificationStatus = ModelIdentificationStatus.SCENARIO_ONLY,
    ):
        super().__init__(price_min, price_max, currency, identification_status)
        if base_quantity <= 0:
            raise ValueError(f"base_quantity must be positive, got {base_quantity}")
        if base_price <= 0:
            raise ValueError(f"base_price must be positive, got {base_price}")
        self.base_price = Decimal(base_price)
        self.base_quantity = int(base_quantity)
        self.elasticity = Decimal(elasticity)

    def evaluate_quantity(self, price: Decimal) -> int:
        self.check_bounds(price)
        p_ratio = float(price / self.base_price)
        q = float(self.base_quantity) * (p_ratio ** float(self.elasticity))
        return max(0, int(round(q)))


class LinearDemand(DemandModel):
    """Linear downward sloping demand: Q(P) = max(0, round(a - b * P))."""

    def __init__(
        self,
        intercept: Decimal,
        slope: Decimal,
        price_min: Decimal,
        price_max: Decimal,
        currency: str,
        identification_status: ModelIdentificationStatus = ModelIdentificationStatus.SCENARIO_ONLY,
    ):
        super().__init__(price_min, price_max, currency, identification_status)
        if slope <= 0:
            raise ValueError(f"Downward-sloping demand requires positive slope b, got {slope}")
        self.intercept = Decimal(intercept)
        self.slope = Decimal(slope)

    def evaluate_quantity(self, price: Decimal) -> int:
        self.check_bounds(price)
        q = self.intercept - self.slope * Decimal(price)
        return max(0, int(round(float(q))))


class LogitChoiceDemand(DemandModel):
    """Multinomial logit choice model with competitor substitutes (SRS-031)."""

    def __init__(
        self,
        base_utility: float,
        price_sensitivity: float,
        competitor_utilities: List[float],
        competitor_prices: List[float],
        total_market_size: int,
        price_min: Decimal,
        price_max: Decimal,
        currency: str,
        identification_status: ModelIdentificationStatus = ModelIdentificationStatus.SCENARIO_ONLY,
    ):
        super().__init__(price_min, price_max, currency, identification_status)
        if len(competitor_utilities) != len(competitor_prices):
            raise ValueError("Competitor utilities and prices must have identical length")
        if total_market_size <= 0:
            raise ValueError("total_market_size must be positive")
        self.base_utility = float(base_utility)
        self.price_sensitivity = float(price_sensitivity)
        self.competitor_utilities = [float(u) for u in competitor_utilities]
        self.competitor_prices = [float(p) for p in competitor_prices]
        self.total_market_size = int(total_market_size)

    def evaluate_choice_probability(self, price: Decimal) -> float:
        self.check_bounds(price)
        our_val = self.base_utility - self.price_sensitivity * float(price)
        # Numerical stability via max shift
        comp_vals = [
            u - self.price_sensitivity * p
            for u, p in zip(self.competitor_utilities, self.competitor_prices)
        ]
        all_vals = [our_val] + comp_vals
        max_val = max(all_vals)
        
        our_exp = math.exp(our_val - max_val)
        sum_exp = our_exp + sum(math.exp(v - max_val) for v in comp_vals)
        return our_exp / sum_exp

    def evaluate_quantity(self, price: Decimal) -> int:
        prob = self.evaluate_choice_probability(price)
        return max(0, int(round(prob * self.total_market_size)))
