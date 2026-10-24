"""Jurisdiction / currency / tax-basis context chosen by the user (owner decision OD: default USA).

No tax RATES are hardcoded: rates vary by locality/product and must come from user input or a
cited source. `price_convention` is the typical consumer-price display convention and is only a
default suggestion the user must confirm. Tax basis values match core.schema (NET/GROSS/...).
"""
from __future__ import annotations

from dataclasses import dataclass

TAX_BASES = ("NET", "GROSS", "NOT_APPLICABLE", "UNKNOWN")
DEFAULT_COUNTRY = "US"


@dataclass(frozen=True)
class Jurisdiction:
    code: str
    name: str
    currency: str
    tax_regime: str
    typical_basis: str  # typical consumer price display; user must confirm
    note: str


_J = (
    Jurisdiction("US", "United States", "USD", "State/local sales tax (varies by state, product)", "NET",
                 "Shelf prices usually exclude sales tax; it is added at checkout and varies by state."),
    Jurisdiction("CA", "Canada", "CAD", "GST/HST/PST (federal + provincial)", "NET",
                 "Prices usually exclude GST/HST/PST."),
    Jurisdiction("GB", "United Kingdom", "GBP", "VAT", "GROSS", "Consumer prices usually include VAT."),
    Jurisdiction("EU", "European Union (specify member state)", "EUR", "VAT (rate set per member state)",
                 "GROSS", "Consumer prices usually include VAT; rates differ by country and product."),
    Jurisdiction("IN", "India", "INR", "GST (rate varies by product category)", "GROSS",
                 "Consumer prices (MRP) usually include GST."),
    Jurisdiction("AU", "Australia", "AUD", "GST", "GROSS", "Consumer prices usually include GST."),
    Jurisdiction("SG", "Singapore", "SGD", "GST", "GROSS", "Consumer prices usually include GST."),
    Jurisdiction("AE", "United Arab Emirates", "AED", "VAT", "GROSS", "Consumer prices usually include VAT."),
    Jurisdiction("JP", "Japan", "JPY", "Consumption tax", "GROSS", "Consumer prices usually tax-inclusive."),
    Jurisdiction("BR", "Brazil", "BRL", "Multiple indirect taxes (ICMS, IPI, PIS/COFINS, ISS)", "GROSS",
                 "Complex multi-layer taxes; specify details."),
    Jurisdiction("MX", "Mexico", "MXN", "IVA (VAT)", "GROSS", "Consumer prices usually include IVA."),
    Jurisdiction("ZA", "South Africa", "ZAR", "VAT", "GROSS", "Consumer prices usually include VAT."),
    Jurisdiction("OTHER", "Other / custom", "", "User-specified", "UNKNOWN",
                 "Provide currency and tax details yourself; unknown tax basis blocks definitive margin claims."),
)
_BY = {j.code: j for j in _J}


def list_jurisdictions() -> list[dict]:
    return [j.__dict__ | {"is_default": j.code == DEFAULT_COUNTRY} for j in _J]


def resolve_context(country: str | None = None, currency: str | None = None,
                    tax_basis: str | None = None, tax_notes: str | None = None) -> dict:
    """Return the operating context. Anything not user-specified is flagged DEFAULTED, not 'known'."""
    defaulted: list[str] = []
    code = (country or "").strip().upper()
    if code not in _BY:
        if code:
            raise ValueError(f"unsupported country code {code!r}; use OTHER and specify currency/tax")
        code = DEFAULT_COUNTRY
        defaulted.append("country")
    j = _BY[code]
    cur = (currency or "").strip().upper()
    if cur:
        if len(cur) != 3 or not cur.isalpha():
            raise ValueError("currency must be a 3-letter ISO 4217 code")
    else:
        cur = j.currency
        if not cur:
            raise ValueError("currency is required when country is OTHER")
        defaulted.append("currency")
    basis = (tax_basis or "").strip().upper()
    if basis:
        if basis not in TAX_BASES:
            raise ValueError(f"tax_basis must be one of {TAX_BASES}")
    else:
        basis = j.typical_basis
        defaulted.append("tax_basis")
    return {
        "country": code, "country_name": j.name, "currency": cur, "tax_regime": j.tax_regime,
        "tax_basis": basis, "tax_notes": (tax_notes or "").strip()[:500],
        "defaulted_fields": defaulted,
        "defaults_are_assumptions": bool(defaulted),
    }


def context_preamble(ctx: dict) -> str:
    """Short, structured text handed to the analysis so it reports in the user's frame."""
    d = ("; DEFAULTED (not confirmed by user): " + ", ".join(ctx["defaulted_fields"])) \
        if ctx["defaulted_fields"] else ""
    notes = f" Tax notes: {ctx['tax_notes']}." if ctx["tax_notes"] else ""
    return (f"[Operating context: home market {ctx['country_name']}; currency {ctx['currency']}; "
            f"tax regime {ctx['tax_regime']}; price basis {ctx['tax_basis']}{d}.{notes}]")
