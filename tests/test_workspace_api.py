"""Public API checks for the document-led workspace."""
import os
from pathlib import Path
import time

from fastapi.testclient import TestClient


os.environ["STRATEGY_DB_PATH"] = str(Path(__file__).parent / ".testdata" / "cases.sqlite3")
os.environ["STRATEGY_DEMO_EMAIL"] = "owner@example.test"
os.environ["STRATEGY_DEMO_PASSWORD"] = "correct-horse-battery-staple"

from main import app  # noqa: E402


def test_private_draft_requires_login_and_survives_readback():
    with TestClient(app) as client:
        assert client.post("/api/cases", json={}).status_code == 401
        login = client.post(
            "/api/auth/login",
            json={"email": "owner@example.test", "password": "correct-horse-battery-staple"},
        )
        assert login.status_code == 200
        created = client.post("/api/cases", json={})
        assert created.status_code == 201
        case_id = created.json()["id"]
        saved = client.get(f"/api/cases/{case_id}")
        assert saved.status_code == 200
        assert saved.json()["status"] == "draft"
        client.post("/api/auth/logout")
        assert client.get(f"/api/cases/{case_id}").status_code == 401


def test_documents_attach_to_one_private_case_and_document_only_waits_for_question(monkeypatch):
    import workspace_api

    monkeypatch.setattr(workspace_api, "ingest_document", lambda path, case_id, filename: {
        "chunk_count": 2, "text_preview": path.read_text(encoding="utf-8")[:100]
    })
    async def understand_source(state):
        return {"twin": {"companies": [{"id": "company-1", "type": "Company", "name": "Nila Home",
                    "attributes": {"geography": "India"}, "epistemic": {"geography": "known"}}],
                    "products": [], "segments": [], "competitors": [], "constraints": [], "objectives": [],
                    "unknowns": ["Observed CAC"]},
                "events": [{"type": "agent_complete", "used_passages": [{"source": "test-source",
                            "doc_id": "span-1", "excerpt": "Nila Home sells storage kits"}]}]}
    monkeypatch.setattr(workspace_api, "understand_node", understand_source)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={
            "email": "owner@example.test", "password": "correct-horse-battery-staple"
        })
        case_id = client.post("/api/cases").json()["id"]
        for name in ("company.txt", "costs.md"):
            uploaded = client.post(f"/api/cases/{case_id}/documents", files={
                "file": (name, b"Nila Home sells a kitchen storage starter kit in India. Unit cost INR 180.")
            })
            assert uploaded.status_code == 201
        started = client.post(f"/api/cases/{case_id}/start", json={"question": ""})
        assert started.status_code == 200
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            saved = client.get(f"/api/cases/{case_id}").json()
            if saved["status"] != "preparing_source":
                break
            time.sleep(.05)
        assert saved["status"] == "awaiting_question"
        assert len(saved["documents"]) == 2
        assert saved["source_snapshot"]["version"] == 2
        assert saved["source_snapshot"]["suggested_questions"]
        assert saved["source_snapshot"]["entities"][0]["name"] == "Nila Home"
        assert saved["source_snapshot"]["used_passages"][0]["doc_id"] == "span-1"


def test_document_only_case_stays_actionable_when_source_llm_is_unavailable(monkeypatch):
    import workspace_api

    monkeypatch.setattr(workspace_api, "ingest_document", lambda *args: {"chunk_count": 1})
    async def unavailable(_state):
        raise workspace_api.LLMUnavailableError("provider temporarily unavailable")
    monkeypatch.setattr(workspace_api, "understand_node", unavailable)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={
            "email": "owner@example.test", "password": "correct-horse-battery-staple"
        })
        case_id = client.post("/api/cases").json()["id"]
        assert client.post(f"/api/cases/{case_id}/documents", files={
            "file": ("brief.txt", b"Nila Home plans a launch in India.")
        }).status_code == 201
        client.post(f"/api/cases/{case_id}/start", json={"question": ""})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            saved = client.get(f"/api/cases/{case_id}").json()
            if saved["status"] != "preparing_source":
                break
            time.sleep(.05)
        assert saved["status"] == "awaiting_question"
        assert saved["source_snapshot"]["status"] == "indexed_pending_analysis"
        assert any(event["type"] == "source_twin_deferred" for event in saved["events"])


def test_completed_case_can_propose_scenario_and_export_without_replacing_run():
    import workspace_store as store

    with TestClient(app) as client:
        owner = client.post("/api/auth/login", json={
            "email": "owner@example.test", "password": "correct-horse-battery-staple"
        }).json()
        case_id = client.post("/api/cases").json()["id"]
        store.update_case(case_id, question="Which launch channel should Nila Home use?", status="completed")
        run = store.add_run(case_id, "completed", result={
            "recommendation": "Test retail first", "rationale": "Lower modeled downside",
            "simulations": [{"hypothesis_id": "H1", "avg_profit": 12000, "p10_profit": -1000,
                             "p50_profit": 11000, "p90_profit": 23000, "prob_positive": 0.8}],
            "evidence": [{"id": "E1", "source_type": "fixture", "excerpt": "Illustrative demand"}],
        }, assumptions={"cac_inr": 300})
        proposal = client.post(f"/api/cases/{case_id}/messages", json={"content": "What if CAC is ₹450?"})
        assert proposal.status_code == 200
        assert proposal.json()["type"] == "scenario_proposal"
        assert proposal.json()["overrides"] == {"cac_inr": 450.0}
        assert len(client.get(f"/api/cases/{case_id}").json()["runs"]) == 1
        csv_export = client.get(f"/api/cases/{case_id}/exports/csv?run_id={run['id']}")
        assert csv_export.status_code == 200
        assert "H1" in csv_export.text
        json_export = client.get(f"/api/cases/{case_id}/exports/json?run_id={run['id']}")
        assert json_export.json()["run"]["id"] == run["id"]
        assert json_export.json()["fixture_data_present"] is True
        pdf_export = client.get(f"/api/cases/{case_id}/exports/pdf?run_id={run['id']}")
        assert pdf_export.content.startswith(b"%PDF")
        second = store.create_user("other@example.test", "another-long-password")
        assert second
        client.post("/api/auth/logout")
        client.post("/api/auth/login", json={"email": "other@example.test", "password": "another-long-password"})
        assert client.get(f"/api/cases/{case_id}").status_code == 404
        assert client.get(f"/api/cases/{case_id}/exports/json?run_id={run['id']}").status_code == 404


def test_case_pauses_for_review_then_finishes_with_auditable_results(monkeypatch):
    import agents.understand as understand
    import agents.planner as planner
    import agents.strategy as strategy
    import agents.devil as devil
    import agents.decision as decision

    class Model:
        async def complete_json(self, system, user, temperature=None):
            if "extract structured" in system.lower() or "read a company document" in system.lower():
                return {"company": {"name": "Nila Home"}, "product": {"name": "Storage kit"},
                        "financial_params": {"base_demand": 1000, "elasticity": -1.2,
                                             "unit_cost_inr": 180, "fixed_cost_inr": 45000,
                                             "cac_inr": 300, "cash_available_inr": 300000},
                        "segments": [], "competitors": [], "constraints": [], "objectives": [], "unknowns": ["Observed CAC"]}
            if "research planner" in system.lower():
                return {"research_tasks": [], "planning_rationale": "No external tasks in fixture test"}
            if "strategic options" in system.lower():
                return {"hypotheses": [
                    {"title": "Direct", "price_inr": 699, "channel": "d2c", "initial_confidence": .6},
                    {"title": "Retail", "price_inr": 599, "channel": "retail", "initial_confidence": .5},
                ]}
            if "devil's advocate" in system.lower():
                return {"challenges": [{"weakness": "CAC remains unobserved", "assumption_targeted": "CAC",
                                         "severity": "moderate"}], "verdict": "uncertain", "triggers_replan": False}
            return {"recommendation": "Run a capped channel pilot", "rationale": "Compare observed economics",
                    "selected_hypothesis_title": "Retail", "confidence": .6,
                    "key_assumptions": ["CAC must be measured"], "open_questions": ["Observed CAC"]}

    model = Model()
    for module in (understand, planner, strategy, devil, decision):
        monkeypatch.setattr(module, "get_llm_provider", lambda: model)
    monkeypatch.setattr(understand, "retrieve_for_question", lambda *args: [])
    monkeypatch.setattr(strategy, "retrieve_for_question", lambda *args: [])

    with TestClient(app) as client:
        client.post("/api/auth/login", json={
            "email": "owner@example.test", "password": "correct-horse-battery-staple"
        })
        case_id = client.post("/api/cases").json()["id"]
        response = client.post(f"/api/cases/{case_id}/start", json={
            "question": "Which price and channel should Nila Home use for its launch?"
        })
        assert response.status_code == 200

        def wait_status(expected):
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                saved = client.get(f"/api/cases/{case_id}").json()
                if saved["status"] == expected or saved["status"] == "failed":
                    return saved
                time.sleep(.1)
            raise AssertionError(f"Case never reached {expected}")

        paused = wait_status("awaiting_approval")
        assert paused["status"] == "awaiting_approval", paused["runs"][-1]["result"]
        assert paused["approval"]["values"]["pilot_budget_cap_inr"] == 25000
        assert any(event["type"] == "stage_record" for event in paused["events"])
        resumed = client.post(f"/api/cases/{case_id}/approve", json={
            "values": {**paused["approval"]["values"], "cac_inr": 450}
        })
        assert resumed.status_code == 200
        finished = wait_status("completed")
        assert finished["status"] == "completed", finished["runs"][-1]["result"]
        result = finished["runs"][-1]["result"]
        assert len(result["sensitivity"]) == 9
        assert result["pilot"]["budget_cap_inr"] == 25000
        assert result["pilot"]["human_action_required"] is True
        assert finished["runs"][-1]["assumptions"]["cac_inr"] == 450
        original_run_id = finished["runs"][-1]["id"]
        proposed = client.post(f"/api/cases/{case_id}/messages", json={"content": "What if CAC is ₹600?"}).json()
        assert proposed["type"] == "scenario_proposal"
        confirmed = client.post(f"/api/cases/{case_id}/runs", json={
            "base_run_id": proposed["base_run_id"], "overrides": proposed["overrides"]
        })
        assert confirmed.status_code == 201
        rerun = wait_status("completed")
        assert len(rerun["runs"]) == 2
        assert rerun["runs"][0]["id"] == original_run_id
        assert rerun["runs"][1]["assumptions"]["cac_inr"] == 600
