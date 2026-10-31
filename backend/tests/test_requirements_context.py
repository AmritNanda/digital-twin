"""Start-screen requirements guide + jurisdiction context (SRS-007/008, AT-003 part). FIXTURE text only."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dtp.jurisdiction import context_preamble, list_jurisdictions, resolve_context
from dtp.requirements_guide import guide, scan_text


def test_default_is_usa_usd_and_flagged_defaulted():
    c = resolve_context()
    assert (c["country"], c["currency"], c["tax_basis"]) == ("US", "USD", "NET")
    assert set(c["defaulted_fields"]) == {"country", "currency", "tax_basis"}
    assert c["defaults_are_assumptions"] is True
    assert "DEFAULTED" in context_preamble(c)


def test_user_choices_override_and_are_not_flagged():
    c = resolve_context("in", "inr", "gross", "GST 18% on this category")
    assert (c["country"], c["currency"], c["tax_basis"]) == ("IN", "INR", "GROSS")
    assert c["defaulted_fields"] == [] and "DEFAULTED" not in context_preamble(c)


def test_partial_choice_flags_only_remaining():
    c = resolve_context("GB")
    assert c["currency"] == "GBP" and c["defaulted_fields"] == ["currency", "tax_basis"]


@pytest.mark.parametrize("args", [("ZZ",), ("US", "DOLLAR"), ("US", "US1"), ("US", "USD", "maybe")])
def test_invalid_context_rejected(args):
    with pytest.raises(ValueError):
        resolve_context(*args)


def test_other_requires_currency_and_unknown_basis_default():
    with pytest.raises(ValueError):
        resolve_context("OTHER")
    c = resolve_context("OTHER", "CHF")
    assert c["tax_basis"] == "UNKNOWN"


def test_no_tax_rates_hardcoded():
    assert all("%" not in j["tax_regime"] + j["note"] for j in list_jurisdictions())


def test_guide_has_critical_items_and_default_note():
    g = guide()
    ids = {i["id"] for i in g["items"]}
    assert {"objective", "unit_cost", "fixed_costs", "currency_tax", "horizon"} <= ids
    assert any(i["critical"] for i in g["items"]) and "United States" in g["default_note"]


def test_scan_reports_missing_critical_and_never_claims_extraction():
    r = scan_text("Should we launch? Unit cost 8 dollars.")
    assert "fixed_costs" in r["possibly_missing_critical"]
    assert "unit_cost" not in r["possibly_missing_critical"]
    assert "not extraction" in r["disclaimer"]
    assert len(scan_text("")["possibly_missing_critical"]) == sum(i["critical"] for i in guide()["items"])


def test_api_endpoints():
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    try:
        import main  # heavy imports (chroma etc.)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"legacy app import unavailable: {e}")
    c = fastapi_testclient.TestClient(main.app)
    assert c.get("/api/requirements").json()["items"]
    j = c.get("/api/jurisdictions").json()
    assert j["default"] == "US"
    assert c.post("/api/requirements/check", json={"text": "budget 5000"}).status_code == 200
    caps = c.get("/api/capabilities").json()["capabilities"]
    assert all("key" not in repr(x).lower() or "missing_env" in x for x in caps)
    r = c.post("/api/case", json={"question": "What price should we choose?", "country": "ZZ"})
    assert r.status_code == 400
    home = c.get("/")
    assert home.status_code == 200
    marker = 'id="root"' if (main.FRONTEND_DIST / "index.html").exists() else "static/requirements.js"
    assert marker in home.text


@pytest.mark.parametrize("path,payload", [
    ("/api/simulation/evaluate", {"draw_count": 0}),
    ("/api/simulation/evaluate", {"price_std": 0}),
    ("/api/cashflow/evaluate", {"total_periods": -1}),
    ("/api/cashflow/evaluate", {"units_per_period": -1}),
])
def test_numerical_api_rejects_invalid_inputs(path, payload):
    from main import app
    from fastapi.testclient import TestClient

    assert TestClient(app).post(path, json=payload).status_code == 422


def test_numerical_api_defaults_execute():
    from main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    assert client.post("/api/simulation/evaluate", json={}).status_code == 200
    assert client.post("/api/cashflow/evaluate", json={}).status_code == 200
