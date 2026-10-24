"""Multi-period cash flow, inventory conservation, and liquidity engine (SRS-032, SRS-033, AT-024).

Enforces strict separation between accrual accounting profit and cash liquidity:
- Physical inventory conservation: beginning + receipts - fulfilled - losses == ending
- Working capital timing (AP supplier lag / advances, AR customer receivables lag)
- Explicit return/refund flows and payment transaction fees
- Liquidity constraints: detection of minimum cash breaches and calculation of funding requirements
- Accounting profit cannot override liquidity constraints.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import List, Optional, Dict, Any

CENT = Decimal("0.01")


class InventoryConservationError(ValueError):
    """Raised when inventory physical balance conservation is violated."""
    pass


class LiquidityBreachError(ValueError):
    """Raised when cash balance breaches required minimum liquidity buffer."""
    pass


@dataclass
class PeriodInput:
    period: int
    demand_units: int
    procurement_receipt_units: int
    procurement_order_units: int
    unit_purchase_cost: Decimal
    unit_selling_price: Decimal
    unit_cogs: Decimal
    unit_fulfillment: Decimal
    payment_fee_rate: Decimal
    acquisition_cost_per_unit: Decimal
    fixed_operating_costs: Decimal
    return_rate: Decimal = Decimal("0.00")
    refund_per_unit: Optional[Decimal] = None
    inventory_losses: int = 0
    capex: Decimal = Decimal("0.00")
    financing_inflow: Decimal = Decimal("0.00")
    
    # Timing parameters:
    # ap_lag_periods: 0 = paid in receipt period, 1 = paid in next period, -1 = advance (paid 1 period before receipt)
    ap_lag_periods: int = 0
    # ar_lag_periods: 0 = customer pays cash immediately, 1 = cash collected in next period
    ar_lag_periods: int = 0


@dataclass
class CashFlowPeriod:
    period: int
    # Inventory
    beginning_inventory: int
    procurement_receipts: int
    fulfilled_units: int
    lost_sales_units: int
    inventory_losses: int
    ending_inventory: int
    
    # Accrual Accounting (P&L)
    gross_revenue: Decimal
    returns_value: Decimal
    net_revenue: Decimal
    cogs_recognized: Decimal
    fulfillment_expense: Decimal
    payment_fees: Decimal
    acquisition_expense: Decimal
    contribution_margin: Decimal
    fixed_costs: Decimal
    operating_profit: Decimal
    
    # Cash Flow Statement
    cash_opening: Decimal
    cash_inflows_collections: Decimal
    cash_inflows_financing: Decimal
    total_cash_inflows: Decimal
    
    cash_outflows_procurement: Decimal
    cash_outflows_fulfillment: Decimal
    cash_outflows_payment_fees: Decimal
    cash_outflows_acquisition: Decimal
    cash_outflows_fixed_costs: Decimal
    cash_outflows_refunds: Decimal
    cash_outflows_capex: Decimal
    total_cash_outflows: Decimal
    
    net_cash_flow: Decimal
    cash_closing: Decimal
    
    # Working capital state at period close
    accounts_receivable_closing: Decimal
    accounts_payable_closing: Decimal
    inventory_asset_value_closing: Decimal


@dataclass
class CashFlowResult:
    currency: str
    periods: List[CashFlowPeriod]
    total_net_revenue: Decimal
    total_cogs: Decimal
    total_operating_profit: Decimal
    opening_cash: Decimal
    ending_cash: Decimal
    min_cash_balance: Decimal
    min_cash_period: int
    min_cash_reserve: Decimal
    liquidity_breached: bool
    funding_requirement: Decimal
    inventory_conserved: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "currency": self.currency,
            "period_count": len(self.periods),
            "total_net_revenue": str(self.total_net_revenue.quantize(CENT, ROUND_HALF_UP)),
            "total_cogs": str(self.total_cogs.quantize(CENT, ROUND_HALF_UP)),
            "total_operating_profit": str(self.total_operating_profit.quantize(CENT, ROUND_HALF_UP)),
            "opening_cash": str(self.opening_cash.quantize(CENT, ROUND_HALF_UP)),
            "ending_cash": str(self.ending_cash.quantize(CENT, ROUND_HALF_UP)),
            "min_cash_balance": str(self.min_cash_balance.quantize(CENT, ROUND_HALF_UP)),
            "min_cash_period": self.min_cash_period,
            "min_cash_reserve": str(self.min_cash_reserve.quantize(CENT, ROUND_HALF_UP)),
            "liquidity_breached": self.liquidity_breached,
            "funding_requirement": str(self.funding_requirement.quantize(CENT, ROUND_HALF_UP)),
            "inventory_conserved": self.inventory_conserved,
        }


class CashFlowEngine:
    """Deterministic multi-period inventory, accrual profit, and cash liquidity solver."""

    def __init__(self, currency: str, initial_cash: Decimal, initial_inventory: int = 0, min_cash_reserve: Decimal = Decimal("0.00")):
        if not currency:
            raise ValueError("currency required")
        self.currency = currency
        self.initial_cash = Decimal(initial_cash)
        self.initial_inventory = int(initial_inventory)
        self.min_cash_reserve = Decimal(min_cash_reserve)

    def run(self, inputs: List[PeriodInput]) -> CashFlowResult:
        if not inputs:
            raise ValueError("At least one period input is required")

        n_periods = len(inputs)
        # Pre-allocate scheduled cash AP (supplier payables) and AR (customer receivables)
        # We index from 0 to n_periods + 5 to allow lags spilling past simulation horizon
        ap_schedule: Dict[int, Decimal] = {p: Decimal("0.00") for p in range(n_periods + 10)}
        ar_schedule: Dict[int, Decimal] = {p: Decimal("0.00") for p in range(n_periods + 10)}

        # Schedule AP based on procurement orders and payment terms
        for p_idx, inp in enumerate(inputs):
            procurement_spend = Decimal(inp.procurement_receipt_units) * Decimal(inp.unit_purchase_cost)
            target_period = p_idx + inp.ap_lag_periods
            if target_period < 0:
                raise ValueError(f"Advance AP lag {inp.ap_lag_periods} in period {p_idx} leads to negative time")
            ap_schedule[target_period] = ap_schedule[target_period] + procurement_spend

        current_inventory = self.initial_inventory
        current_cash = self.initial_cash
        
        periods_out: List[CashFlowPeriod] = []
        total_net_rev = Decimal("0.00")
        total_cogs = Decimal("0.00")
        total_profit = Decimal("0.00")
        
        min_cash = current_cash
        min_cash_period = 0

        # Cumulative tracking for reconciliation
        cumulative_receivables_recognized = Decimal("0.00")
        cumulative_receivables_collected = Decimal("0.00")
        cumulative_payables_incurred = Decimal("0.00")
        cumulative_payables_paid = Decimal("0.00")

        for p_idx, inp in enumerate(inputs):
            # 1. Physical Inventory Dynamics & Conservation (SRS-032)
            beg_inv = current_inventory
            receipts = int(inp.procurement_receipt_units)
            available = beg_inv + receipts
            demand = int(inp.demand_units)
            
            fulfilled = min(available, demand)
            lost_sales = max(0, demand - available)
            losses = int(inp.inventory_losses)
            
            ending_inv = available - fulfilled - losses
            if ending_inv < 0:
                raise InventoryConservationError(
                    f"Period {inp.period}: Ending inventory {ending_inv} < 0 (beg={beg_inv}, receipts={receipts}, fulfilled={fulfilled}, losses={losses})"
                )
            
            # Conservation check
            if beg_inv + receipts - fulfilled - losses != ending_inv:
                raise InventoryConservationError(f"Period {inp.period}: Inventory conservation failed")
            
            current_inventory = ending_inv

            # 2. Accrual Accounting (P&L) (SRS-033)
            gross_rev = Decimal(fulfilled) * Decimal(inp.unit_selling_price)
            # Returns calculation
            returned_units = Decimal(fulfilled) * Decimal(inp.return_rate)
            refund_unit_val = inp.refund_per_unit if inp.refund_per_unit is not None else inp.unit_selling_price
            returns_val = returned_units * refund_unit_val
            net_rev = gross_rev - returns_val
            
            # Cost of goods sold recognized for units fulfilled
            cogs = Decimal(fulfilled) * Decimal(inp.unit_cogs)
            fulfillment_exp = Decimal(fulfilled) * Decimal(inp.unit_fulfillment)
            payment_fee = gross_rev * Decimal(inp.payment_fee_rate)
            acq_exp = Decimal(fulfilled) * Decimal(inp.acquisition_cost_per_unit)
            
            fixed_cost = Decimal(inp.fixed_operating_costs)
            contribution = net_rev - cogs - fulfillment_exp - payment_fee - acq_exp
            op_profit = contribution - fixed_cost
            
            total_net_rev += net_rev
            total_cogs += cogs
            total_profit += op_profit

            # 3. Cash Flow Collections & Timing (SRS-033, AT-024)
            # Schedule customer sales collections into AR
            net_cash_sales_value = net_rev
            collection_period = p_idx + inp.ar_lag_periods
            ar_schedule[collection_period] = ar_schedule[collection_period] + net_cash_sales_value
            cumulative_receivables_recognized += net_cash_sales_value

            cash_opening = current_cash
            cash_in_collections = ar_schedule.get(p_idx, Decimal("0.00"))
            cumulative_receivables_collected += cash_in_collections
            
            cash_in_financing = Decimal(inp.financing_inflow)
            tot_inflows = cash_in_collections + cash_in_financing

            # Cash outflows
            # Supplier procurement outflow from pre-scheduled AP
            cash_out_procurement = ap_schedule.get(p_idx, Decimal("0.00"))
            proc_incurred = Decimal(receipts) * Decimal(inp.unit_purchase_cost)
            cumulative_payables_incurred += proc_incurred
            cumulative_payables_paid += cash_out_procurement

            cash_out_fulfillment = fulfillment_exp
            cash_out_fees = payment_fee
            cash_out_acq = acq_exp
            cash_out_fixed = fixed_cost
            cash_out_refunds = returns_val if inp.ar_lag_periods == 0 else Decimal("0.00") # already net if immediate
            cash_out_capex = Decimal(inp.capex)

            tot_outflows = (
                cash_out_procurement
                + cash_out_fulfillment
                + cash_out_fees
                + cash_out_acq
                + cash_out_fixed
                + cash_out_capex
            )

            net_cf = tot_inflows - tot_outflows
            cash_closing = cash_opening + net_cf
            current_cash = cash_closing

            if cash_closing < min_cash:
                min_cash = cash_closing
                min_cash_period = inp.period

            # Outstanding balance sheet items at close
            ar_closing = cumulative_receivables_recognized - cumulative_receivables_collected
            ap_closing = cumulative_payables_incurred - cumulative_payables_paid
            inv_asset_val = Decimal(ending_inv) * Decimal(inp.unit_purchase_cost)

            period_summary = CashFlowPeriod(
                period=inp.period,
                beginning_inventory=beg_inv,
                procurement_receipts=receipts,
                fulfilled_units=fulfilled,
                lost_sales_units=lost_sales,
                inventory_losses=losses,
                ending_inventory=ending_inv,
                gross_revenue=gross_rev,
                returns_value=returns_val,
                net_revenue=net_rev,
                cogs_recognized=cogs,
                fulfillment_expense=fulfillment_exp,
                payment_fees=payment_fee,
                acquisition_expense=acq_exp,
                contribution_margin=contribution,
                fixed_costs=fixed_cost,
                operating_profit=op_profit,
                cash_opening=cash_opening,
                cash_inflows_collections=cash_in_collections,
                cash_inflows_financing=cash_in_financing,
                total_cash_inflows=tot_inflows,
                cash_outflows_procurement=cash_out_procurement,
                cash_outflows_fulfillment=cash_out_fulfillment,
                cash_outflows_payment_fees=cash_out_fees,
                cash_outflows_acquisition=cash_out_acq,
                cash_outflows_fixed_costs=cash_out_fixed,
                cash_outflows_refunds=cash_out_refunds,
                cash_outflows_capex=cash_out_capex,
                total_cash_outflows=tot_outflows,
                net_cash_flow=net_cf,
                cash_closing=cash_closing,
                accounts_receivable_closing=ar_closing,
                accounts_payable_closing=ap_closing,
                inventory_asset_value_closing=inv_asset_val,
            )
            periods_out.append(period_summary)

        liquidity_breached = min_cash < self.min_cash_reserve
        funding_req = max(Decimal("0.00"), self.min_cash_reserve - min_cash)

        return CashFlowResult(
            currency=self.currency,
            periods=periods_out,
            total_net_revenue=total_net_rev,
            total_cogs=total_cogs,
            total_operating_profit=total_profit,
            opening_cash=self.initial_cash,
            ending_cash=current_cash,
            min_cash_balance=min_cash,
            min_cash_period=min_cash_period,
            min_cash_reserve=self.min_cash_reserve,
            liquidity_breached=liquidity_breached,
            funding_requirement=funding_req,
            inventory_conserved=True,
        )
