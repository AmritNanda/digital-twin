"""Exact decimal unit economics (SRS-033, AT-023). Origin of golden values: FIXTURE.

Profit is NOT cash. This module computes accounting profit only; cash timing needs
a separate model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


class CurrencyMismatch(ValueError):
    pass


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self):
        if not self.currency:
            raise ValueError("currency required")
        object.__setattr__(self, "amount", Decimal(self.amount))

    def _chk(self, o: "Money"):
        if self.currency != o.currency:
            raise CurrencyMismatch(f"{self.currency} vs {o.currency}: conversion needs a dated rate model")

    def __add__(self, o: "Money") -> "Money":
        self._chk(o)
        return Money(self.amount + o.amount, self.currency)

    def __sub__(self, o: "Money") -> "Money":
        self._chk(o)
        return Money(self.amount - o.amount, self.currency)

    def scaled(self, k: Decimal | int) -> "Money":
        return Money(self.amount * Decimal(k), self.currency)

    def rounded(self) -> Decimal:
        return self.amount.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class UnitEconomics:
    price: Decimal
    cogs: Decimal
    fulfillment: Decimal
    payment_fee_rate: Decimal
    acquisition_cost: Decimal
    fixed_costs: Decimal
    units: int
    currency: str
    tax_basis: str = "NET_OF_TAX"

    @property
    def fee_per_unit(self) -> Decimal:
        return self.price * self.payment_fee_rate

    @property
    def contribution_per_unit(self) -> Decimal:
        return self.price - self.cogs - self.fulfillment - self.fee_per_unit - self.acquisition_cost

    @property
    def profit(self) -> Decimal:
        return self.contribution_per_unit * self.units - self.fixed_costs

    @property
    def break_even_units(self) -> int | None:
        """Ceiling of fixed/contribution; None when contribution <= 0 (never negative)."""
        c = self.contribution_per_unit
        if c <= 0:
            return None
        return int((self.fixed_costs / c).to_integral_value(rounding=ROUND_CEILING))

    @property
    def max_cac_for_zero_profit(self) -> Decimal:
        if self.units <= 0:
            raise ValueError("units must be positive")
        return (self.price - self.cogs - self.fulfillment - self.fee_per_unit
                - self.fixed_costs / Decimal(self.units))

    def feasible_at_cac(self, cac: Decimal) -> bool:
        """Exact check (no display rounding)."""
        return cac <= self.max_cac_for_zero_profit

    def with_acquisition_cost(self, cac: Decimal) -> "UnitEconomics":
        """Holds acquired units fixed; spend rises with CAC (see fixture note)."""
        return UnitEconomics(**{**self.__dict__, "acquisition_cost": Decimal(cac)})

    def summary(self) -> dict:
        be = self.break_even_units
        return {
            "currency": self.currency,
            "fee_per_unit": self.fee_per_unit.quantize(CENT, ROUND_HALF_UP),
            "contribution_per_unit": self.contribution_per_unit.quantize(CENT, ROUND_HALF_UP),
            "break_even_units": be,
            "profit": self.profit.quantize(CENT, ROUND_HALF_UP),
            "metric_basis": "ACCOUNTING_PROFIT_NOT_CASH",
        }


def require_finite(x: float) -> float:
    if not math.isfinite(x):
        raise ValueError("non-finite value")
    return x
