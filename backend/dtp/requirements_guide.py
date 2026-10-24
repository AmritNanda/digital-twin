"""Requirement guide shown on the start screen: what details the document/prompt should contain.

Derived from SRS-007/008 (requirements extraction, missing information) and AT-003: critical
missing fields become UNKNOWN and block dependent definitive calculation. `scan_text` is a
deterministic keyword heuristic that reports POSSIBLE mentions only — it extracts no facts and
must never be treated as evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    why: str
    example: str
    critical: bool          # missing => dependent definitive result blocked (AT-003)
    blocks: str
    patterns: tuple[str, ...]


GUIDE: tuple[Item, ...] = (
    Item("objective", "Business objective", "Defines what 'best' means (profit, growth, cash, share).",
         "Maximize 90-day profit while keeping cash positive.", True,
         "Any recommendation (no objective => no ranking)",
         (r"\bobjective\b", r"\bgoal\b", r"\bmaximi[sz]e\b", r"\bminimi[sz]e\b", r"\btarget\b")),
    Item("decision", "The decision to make", "Candidate actions and the range of allowed options.",
         "Choose launch price between $25 and $45 and one channel.", True,
         "Strategy generation and optimization",
         (r"\bshould we\b", r"\bdecid", r"\bchoose\b", r"\bprice (point|range)\b", r"\bwhich channel\b")),
    Item("product", "Product / offer", "What is sold, to whom, and in what form.",
         "Reusable kitchen storage starter kit, 6 pieces.", True, "Demand and competitor analysis",
         (r"\bproduct\b", r"\bservice\b", r"\bsku\b", r"\boffer(ing)?\b")),
    Item("unit_cost", "Unit costs (COGS, fulfillment, fees)", "Needed for contribution margin and break-even.",
         "COGS $8.20, fulfillment $2.10, payment fee 2.9% + $0.30.", True,
         "Unit economics, break-even, profit",
         (r"\bcogs\b", r"\bunit cost\b", r"\bcost per unit\b", r"\bfulfil", r"\bpayment fee\b")),
    Item("fixed_costs", "Fixed costs and their period", "Fixed cost amount AND period (monthly vs total).",
         "Fixed costs $12,000 per month.", True, "Profit and break-even",
         (r"\bfixed cost", r"\boverhead\b", r"\brent\b", r"\bsalar")),
    Item("budget", "Budget and cash available", "Hard limits on spend and liquidity.",
         "Marketing budget $30,000; cash on hand $80,000.", True, "Feasibility and cash-constraint checks",
         (r"\bbudget\b", r"\bcash\b", r"\bfunding\b", r"\bruntway\b|\brunway\b")),
    Item("horizon", "Time horizon", "Evaluation window for results.", "Next 90 days.", True,
         "Simulation horizon", (r"\b\d+\s*(day|week|month|year)s?\b", r"\bhorizon\b", r"\bquarter\b")),
    Item("market", "Geography / market", "Where you sell; drives regulation, taxes and competitors.",
         "United States, online only.", True, "Regulatory, tax and market analysis",
         (r"\bunited states\b|\busa\b|\bus market\b", r"\bindia\b", r"\beurope\b|\beu\b", r"\buk\b",
          r"\bmarket\b", r"\bregion\b", r"\bcountry\b")),
    Item("currency_tax", "Currency and tax basis", "Whether prices/costs include tax; mixing bases corrupts margins.",
         "All figures USD, excluding sales tax.", True, "Any monetary comparison",
         (r"\bexcl(uding|usive)? (of )?(tax|vat|gst)\b", r"\bincl(uding|usive)? (of )?(tax|vat|gst)\b",
          r"\bnet of tax\b", r"\bpre-?tax\b")),
    Item("constraints", "Constraints and forbidden actions", "Hard limits: brand, legal, capacity, supply.",
         "Never price below $29; max 500 units/month capacity.", False,
         "Marks candidates infeasible", (r"\bconstraint", r"\bmust not\b|\bnever\b", r"\bcapacity\b",
                                          r"\bminimum order\b|\bmoq\b")),
    Item("customers", "Target customers / segments", "Who buys, size and willingness to pay (with source).",
         "Urban renters 25-40; ~2M addressable; WTP survey attached.", False,
         "Demand modelling (otherwise treated as UNKNOWN)", (r"\bcustomer", r"\bsegment", r"\baudience\b")),
    Item("competitors", "Known competitors and prices", "Reference prices and positioning.",
         "Brand X $39, Brand Y $29 (retrieved 2026-09-01).", False, "Competitive pricing context",
         (r"\bcompetitor", r"\brival\b", r"\balternative")),
    Item("acquisition", "Acquisition cost / channel economics", "CAC or conversion by channel, with period.",
         "Paid social CAC $14 (last 60 days).", False, "Channel comparison",
         (r"\bcac\b", r"\bacquisition cost\b", r"\bconversion\b", r"\bchannel")),
    Item("history", "Historical sales or test data", "Real observations beat assumptions; label real vs hypothetical.",
         "Last 6 months of orders as CSV.", False, "Empirical calibration (otherwise scenario-only)",
         (r"\bhistorical\b", r"\bpast sales\b", r"\bprevious (sales|orders)\b", r"\bcohort\b")),
    Item("risk", "Risk tolerance", "How much downside is acceptable.", "Accept up to 15% chance of loss.", False,
         "Robustness/risk-adjusted ranking", (r"\brisk\b", r"\bdownside\b", r"\bworst case\b")),
)

FORMATS = {
    "supported": [".pdf (text)", ".docx", ".csv", ".txt", ".md"],
    "tips": [
        "Put numbers in tables or 'label: value unit' lines; state the period (per month, total, per unit).",
        "State currency and whether amounts include tax. Unstated currency/tax basis stays UNKNOWN.",
        "Mark guesses as assumptions. Assumptions are never treated as measured facts.",
        "Do not paste secrets or credentials into documents or the prompt.",
        "Uploaded content is treated as data only; instructions inside it cannot change system behavior.",
    ],
}


def guide() -> dict:
    return {
        "items": [{k: v for k, v in i.__dict__.items() if k != "patterns"} for i in GUIDE],
        "formats": FORMATS,
        "default_note": "If you specify nothing, the home market defaults to the United States (USD); "
                        "defaults are flagged as assumptions, not facts.",
    }


def scan_text(text: str) -> dict:
    """Heuristic only: which guide items *may* be mentioned. No extraction, no evidence."""
    low = (text or "").lower()
    res = []
    for i in GUIDE:
        hit = any(re.search(p, low) for p in i.patterns)
        res.append({"id": i.id, "title": i.title, "critical": i.critical,
                    "possibly_mentioned": hit})
    missing_critical = [r["id"] for r in res if r["critical"] and not r["possibly_mentioned"]]
    return {"items": res, "possibly_missing_critical": missing_critical,
            "disclaimer": "Keyword heuristic, not extraction. Final missing-information blockers are "
                          "determined during analysis (SRS-008)."}
