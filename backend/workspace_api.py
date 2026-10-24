"""Authenticated API for private, versioned decision cases."""
from __future__ import annotations

import os
import asyncio
import uuid
import json
import math
import csv
import io
import re
from html import escape
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, File, Header, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

import workspace_store as store
from config import ROOT_DIR, settings
from rag.ingest import extract_text, ingest_document, get_collection
from agents.graph import run_case
from agents.understand import understand_node
from agents.simulate import simulation_node, sensitivity_grid
from agents.decision import decision_node
from twin import DigitalTwin
from providers.llm import get_llm_provider, LLMUnavailableError

router = APIRouter(prefix="/api")
COOKIE_NAME = "strategy_session"


class LoginRequest(BaseModel):
    email: str
    password: str


class StartRequest(BaseModel):
    question: str = ""


class ApprovalRequest(BaseModel):
    approved: bool = True
    values: dict[str, float]


class MessageRequest(BaseModel):
    content: str
    run_id: str | None = None


class ScenarioRequest(BaseModel):
    base_run_id: str
    overrides: dict[str, float]


class SourceCorrectionRequest(BaseModel):
    entity_id: str
    field: str
    value: str | float | int
    reason: str


def current_user(strategy_session: str | None = Cookie(default=None)) -> dict:
    user = store.session_user(strategy_session)
    if not user:
        raise HTTPException(401, "Sign in to access private cases")
    return user


def owned_case(case_id: str, user: dict) -> dict:
    case = store.get_case(case_id, user["id"])
    if not case:
        raise HTTPException(404, "Case not found")
    return case


@router.post("/auth/login")
def login(body: LoginRequest, response: Response):
    user = store.verify_user(body.email.strip(), body.password)
    if not user:
        raise HTTPException(401, "Invalid email or password")
    token = store.create_session(user["id"])
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="strict", path="/",
        secure=os.getenv("STRATEGY_COOKIE_SECURE", "false").lower() == "true",
        max_age=7 * 24 * 60 * 60,
    )
    return user


@router.post("/auth/logout")
def logout(response: Response, strategy_session: str | None = Cookie(default=None)):
    store.revoke_session(strategy_session)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "signed_out"}


@router.get("/auth/me")
def me(user: dict = Depends(current_user)):
    return user


@router.post("/cases", status_code=201)
def create_case(user: dict = Depends(current_user)):
    return store.create_case(user["id"])


@router.get("/cases/{case_id}")
def read_case(case_id: str, user: dict = Depends(current_user)):
    return owned_case(case_id, user)


ALLOWED_DOCUMENTS = {".pdf", ".docx", ".csv", ".txt", ".md"}
PRIVATE_FILES = ROOT_DIR / "data" / "private_uploads"


def _source_snapshot(case: dict) -> dict:
    documents = case["documents"]
    text = " ".join(doc["preview"] for doc in documents)
    company = "Nila Home" if "nila home" in text.lower() else (documents[0]["filename"].split(".")[0] if documents else "the company")
    if any(word in text.lower() for word in ("product", "launch", "starter kit")):
        suggestions = [f"What price and channel should {company} use for this launch?",
                       f"What small pilot should {company} run before scaling?"]
    else:
        suggestions = [f"Which strategic option best fits {company}'s documented constraints?"]
    return {"version": case["source_snapshot"].get("version", 0) + 1,
            "documents": [{"id": d["id"], "filename": d["filename"], "chunks": d["chunks"],
                           "preview": d["preview"]} for d in documents],
            "suggested_questions": suggestions,
            "entities": [], "facts": [], "unknowns": [],
            "corrections": case["source_snapshot"].get("corrections", []),
            "status": "documents_indexed"}


@router.post("/cases/{case_id}/documents", status_code=201)
async def upload_case_document(case_id: str, file: UploadFile = File(...), user: dict = Depends(current_user)):
    case = owned_case(case_id, user)
    if case["status"] not in {"draft", "awaiting_question"}:
        raise HTTPException(409, "Documents cannot be changed after analysis starts")
    name = Path(file.filename or "document.txt").name
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_DOCUMENTS:
        raise HTTPException(415, "Use PDF, DOCX, CSV, TXT or Markdown")
    if len(case["documents"]) >= 5:
        raise HTTPException(413, "A case can contain at most five documents")
    content = await file.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "Each document must be 20 MB or smaller")
    if sum(d["size"] for d in case["documents"]) + len(content) > 50 * 1024 * 1024:
        raise HTTPException(413, "The total document size must be 50 MB or smaller")
    case_dir = PRIVATE_FILES / user["id"] / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    doc_key = str(uuid.uuid4())
    path = case_dir / f"{doc_key}{suffix}"
    path.write_bytes(content)
    try:
        extracted = await asyncio.to_thread(extract_text, path)
        if not extracted.strip():
            message = "This PDF has no extractable text; upload a text-based copy" if suffix == ".pdf" else "No readable text found in document"
            raise HTTPException(422, message)
        indexed = await asyncio.to_thread(ingest_document, path, case_id, doc_key)
    except Exception as exc:
        path.unlink(missing_ok=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(422, f"Could not process document: {exc}") from exc
    doc = store.add_document(case_id, name, len(content), path, indexed["chunk_count"], extracted[:500])
    updated = store.get_case(case_id, user["id"])
    store.update_case(case_id, source_snapshot=_source_snapshot(updated))
    store.append_event(case_id, {"type": "document_indexed", "stage": "ingest",
                                  "status": "completed", "filename": name, "document_id": doc["id"],
                                  "chunks": doc["chunks"], "source_type": "internal"})
    return doc


@router.delete("/cases/{case_id}/documents/{doc_id}")
def delete_case_document(case_id: str, doc_id: str, user: dict = Depends(current_user)):
    case = owned_case(case_id, user)
    if case["status"] not in {"draft", "awaiting_question"}:
        raise HTTPException(409, "Documents cannot be changed after analysis starts")
    path = store.remove_document(case_id, doc_id)
    if not path:
        raise HTTPException(404, "Document not found")
    get_collection(case_id).delete(where={"source": path.stem})
    path.unlink(missing_ok=True)
    updated = store.get_case(case_id, user["id"])
    store.update_case(case_id, source_snapshot=_source_snapshot(updated))
    return {"status": "removed"}


_RUNNING_TASKS: set[asyncio.Task] = set()


def _dispatch(coroutine):
    task = asyncio.create_task(coroutine)
    _RUNNING_TASKS.add(task)
    task.add_done_callback(_RUNNING_TASKS.discard)


def _enrich_source_snapshot(case: dict, twin: dict, used_passages: list[dict] | None = None) -> dict:
    snapshot = dict(case["source_snapshot"])
    snapshot["entities"] = [entity for group in ("companies", "products", "segments", "competitors", "constraints", "objectives")
                            for entity in twin.get(group, [])]
    snapshot["facts"] = [{"entity_id": item["id"], "field": key, "value": value,
                          "epistemic": item.get("epistemic", {}).get(key, "inferred")}
                         for item in snapshot["entities"] for key, value in item.get("attributes", {}).items()]
    snapshot["unknowns"] = twin.get("unknowns", [])
    source_names = {Path(doc["path"]).stem: doc["id"] for doc in store.list_document_paths(case["id"])}
    snapshot["used_passages"] = [{**passage, "document_id": source_names.get(passage.get("source"))}
                                  for passage in (used_passages or [])]
    snapshot["status"] = "extracted"
    return snapshot


async def _prepare_source(case_id: str, owner_id: str):
    try:
        result = await understand_node({"case_id": case_id,
            "question": "Summarize the company documents and identify possible strategic decisions.",
            "iteration": 0, "llm_calls": 0})
        passages = next((event.get("used_passages", []) for event in result.get("events", [])
                         if event.get("type") == "agent_complete"), [])
        case = store.get_case(case_id, owner_id)
        store.update_case(case_id, source_snapshot=_enrich_source_snapshot(case, result["twin"], passages),
                          status="awaiting_question")
        store.append_event(case_id, {"type": "source_twin_extracted", "stage": "understand",
                                     "status": "completed", "entity_count": len(result["twin"].get("companies", [])) + len(result["twin"].get("products", [])),
                                     "input_refs": [f"document:{doc['id']}" for doc in case["documents"]],
                                     "model_or_tool": settings.llm_model,
                                     "used_passages": passages})
    except LLMUnavailableError as exc:
        # Indexing has completed even when the configured provider is briefly
        # unavailable. Let the owner choose a decision and retain a truthful
        # source snapshot instead of marking an otherwise valid case as failed.
        case = store.get_case(case_id, owner_id)
        snapshot = dict(case["source_snapshot"])
        snapshot.update({
            "status": "indexed_pending_analysis",
            "entities": [],
            "facts": [],
            "unknowns": [
                "Company facts will be extracted when the analysis provider is available.",
            ],
            "used_passages": [{
                "doc_id": f"document:{doc['id']}",
                "document_id": doc["id"],
                "source": doc["filename"],
                "excerpt": doc["preview"],
                "retrieval_method": "document preview",
            } for doc in case["documents"]],
        })
        store.update_case(case_id, source_snapshot=snapshot, status="awaiting_question")
        store.append_event(case_id, {
            "type": "source_twin_deferred", "stage": "understand", "status": "completed",
            "input_refs": [f"document:{doc['id']}" for doc in case["documents"]],
            "message": "Documents are indexed. Company extraction will resume when the analysis provider is available.",
            "provider_error": str(exc),
        })
    except Exception as exc:
        store.update_case(case_id, status="failed")
        store.append_event(case_id, {"type": "error", "stage": "understand", "status": "failed",
                                     "message": f"Could not prepare the company source: {exc}"})


@router.post("/cases/{case_id}/source/corrections")
def correct_source(case_id: str, body: SourceCorrectionRequest,
                   user: dict = Depends(current_user)):
    case = owned_case(case_id, user)
    if case["status"] not in {"completed", "awaiting_question", "draft", "source_changed"}:
        raise HTTPException(409, "Wait for the current analysis to finish")
    snapshot = dict(case["source_snapshot"])
    entities = snapshot.get("entities") or []
    target = next((item for item in entities if item["id"] == body.entity_id), None)
    if not target:
        raise HTTPException(404, "Source entity not found")
    if not body.field.strip() or not body.reason.strip():
        raise HTTPException(422, "A field and reason are required")
    before = target.get("attributes", {}).get(body.field)
    target["attributes"][body.field] = body.value
    corrections = snapshot.setdefault("corrections", [])
    corrections.append({"entity_type": target["type"], "entity_name": target["name"],
                        "field": body.field, "value": body.value, "before": before,
                        "reason": body.reason, "reviewed_by": user["id"]})
    snapshot["version"] = snapshot.get("version", 0) + 1
    snapshot["facts"] = [fact for fact in snapshot.get("facts", [])
                         if not (fact["entity_id"] == target["id"] and fact["field"] == body.field)]
    snapshot["facts"].append({"entity_id": target["id"], "field": body.field,
                              "value": body.value, "epistemic": "known"})
    status = "source_changed" if case["status"] == "completed" else case["status"]
    store.update_case(case_id, source_snapshot=snapshot, status=status)
    store.append_event(case_id, {"type": "source_corrected", "stage": "source",
                                  "status": "completed", "source_version": snapshot["version"],
                                  "entity_id": body.entity_id, "field": body.field,
                                  "state_change": {"from": before, "to": body.value}})
    return store.get_case(case_id, user["id"])


def _complete_result(result: dict, twin_data: dict, assumptions: dict) -> dict:
    final = dict(result)
    twin = DigitalTwin(**twin_data)
    final["sensitivity"] = sensitivity_grid(twin)
    final["pilot"] = {
        "duration_weeks": 4,
        "budget_cap_inr": assumptions.get("pilot_budget_cap_inr", 25000),
        "measure": ["Observed customer acquisition cost", "Conversion", "Unit margin"],
        "stop_condition": f"Do not scale if observed CAC exceeds the approved INR {assumptions.get('cac_inr', 300):g} assumption or unit margin is negative.",
        "human_action_required": True,
    }
    leading = next((h for h in final.get("hypotheses", [])
                    if h.get("title") == final.get("selected_hypothesis")), None)
    final["supporting_evidence_ids"] = leading.get("supporting_evidence_ids", []) if leading else []
    final["counter_evidence_ids"] = leading.get("contradicting_evidence_ids", []) if leading else []
    final["fixture_data_present"] = any(e.get("source_type") == "fixture" for e in final.get("evidence", []))
    return final


async def _execute(case_id: str, run_id: str, question: str, resume: dict | None = None):
    async def emit(event: dict):
        if event.get("type") == "source_twin_extracted":
            with store.database() as db:
                owner_id = db.execute("SELECT owner_id FROM cases WHERE id=?", (case_id,)).fetchone()[0]
            case = store.get_case(case_id, owner_id)
            store.update_case(case_id, source_snapshot=_enrich_source_snapshot(case, event["twin"], event.get("used_passages")))
            event = {"type": "source_twin_extracted", "stage": "understand", "status": "completed",
                     "entity_count": len(store.get_case(case_id, owner_id)["source_snapshot"]["entities"])}
        store.append_event(case_id, event, run_id)

    try:
        with store.database() as db:
            owner_id = db.execute("SELECT owner_id FROM cases WHERE id=?", (case_id,)).fetchone()[0]
        case_before = store.get_case(case_id, owner_id)
        source_version = case_before["source_snapshot"].get("version", 0)
        outcome = await asyncio.wait_for(
            run_case(case_id, question, None, emit, require_approval=True, resume=resume,
                     checkpoint_id=run_id,
                     source_corrections=case_before["source_snapshot"].get("corrections", []),
                     source_document_ids=[doc["id"] for doc in case_before["documents"]]),
            timeout=settings.case_timeout_seconds,
        )
        if outcome.get("error"):
            store.update_run(run_id, status="failed", result=outcome)
            store.update_case(case_id, status="failed")
            return
        twin = outcome.get("twin") or {}
        if outcome["status"] == "awaiting_approval":
            store.update_run(run_id, status="awaiting_approval", twin=twin)
            store.update_case(case_id, status="awaiting_approval", approval=outcome["approval"])
        elif outcome["status"] == "rejected":
            store.update_run(run_id, status="rejected", twin=twin)
            store.update_case(case_id, status="rejected")
        else:
            approved = (outcome.get("approval") or {}).get("values") or {}
            final = _complete_result(outcome.get("result") or {}, twin, approved)
            final["source_version"] = source_version
            store.update_run(run_id, status="completed", result=final, twin=twin, assumptions=approved)
            store.update_case(case_id, status="completed", approval=outcome.get("approval") or {})
            await emit({"type": "case_completed", "stage": "decision", "status": "completed",
                        "run_id": run_id})
    except Exception as exc:
        store.update_run(run_id, status="failed", result={"error": str(exc)})
        store.update_case(case_id, status="failed")
        await emit({"type": "error", "stage": "graph", "status": "failed", "message": str(exc)})


@router.post("/cases/{case_id}/start")
async def start_case(case_id: str, body: StartRequest, user: dict = Depends(current_user)):
    case = owned_case(case_id, user)
    if case["status"] not in {"draft", "awaiting_question", "source_changed"}:
        raise HTTPException(409, "This case has already started")
    question = body.question.strip() or (case["question"] if case["status"] == "source_changed" else "")
    if not question and not case["documents"]:
        raise HTTPException(400, "Add documents or describe the company and decision")
    if not question:
        store.update_case(case_id, status="preparing_source")
        store.append_event(case_id, {"type": "source_preparation_started", "stage": "understand", "status": "running"})
        _dispatch(_prepare_source(case_id, user["id"]))
        return store.get_case(case_id, user["id"])
    if len(question) < 10:
        raise HTTPException(400, "Describe the decision in at least ten characters")
    store.update_case(case_id, question=question, status="running")
    run = store.add_run(case_id, "running")
    store.append_event(case_id, {"type": "analysis_started", "stage": "understand", "status": "running",
                                  "question": question, "source_version": case["source_snapshot"].get("version", 0)}, run["id"])
    _dispatch(_execute(case_id, run["id"], question))
    return store.get_case(case_id, user["id"])


@router.post("/cases/{case_id}/approve")
async def approve_case(case_id: str, body: ApprovalRequest, user: dict = Depends(current_user)):
    case = owned_case(case_id, user)
    if case["status"] != "awaiting_approval":
        raise HTTPException(409, "This case is not waiting for assumption approval")
    reviewed = case["approval"].get("values") or {}
    if set(body.values) != set(reviewed) or any(not math.isfinite(value) for value in body.values.values()):
        raise HTTPException(422, "Review every assumption with finite values")
    if any(body.values[key] < 0 for key in ("base_demand", "cac_inr", "unit_cost_inr", "fixed_cost_inr", "pilot_budget_cap_inr")) or body.values["elasticity"] >= 0:
        raise HTTPException(422, "Costs and demand must be nonnegative; elasticity must be negative")
    run = store.latest_run(case_id)
    store.update_case(case_id, status="running")
    store.update_run(run["id"], status="running")
    store.append_event(case_id, {"type": "approval_submitted", "stage": "approval", "status": "running",
                                  "approved": body.approved, "values": body.values}, run["id"])
    _dispatch(_execute(case_id, run["id"], case["question"], resume={
        "approved": body.approved, "values": body.values, "reviewed_by": user["id"]
    }))
    return store.get_case(case_id, user["id"])


@router.get("/cases/{case_id}/events")
async def stream_case_events(case_id: str, after: int = 0,
                             last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
                             user: dict = Depends(current_user)):
    owned_case(case_id, user)
    cursor = max(after, int(last_event_id or 0))

    async def generate():
        nonlocal cursor
        while True:
            events = store.list_events(case_id, cursor)
            for event in events:
                cursor = event["id"]
                yield f"id: {cursor}\nevent: ledger\ndata: {json.dumps(event, default=str)}\n\n"
            with store.database() as db:
                current = db.execute("SELECT status FROM cases WHERE id=?", (case_id,)).fetchone()
            if not current or current["status"] in {"completed", "failed", "rejected", "awaiting_approval", "awaiting_question"}:
                yield "event: settled\ndata: {}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _scenario_parameters(message: str) -> dict[str, float]:
    patterns = {
        "cac_inr": r"(?:\bCAC\b|customer acquisition cost)[^\d\n]{0,36}(?:₹|INR\s*)?\s*([\d,]+(?:\.\d+)?)",
        "elasticity": r"\belasticity\b[^\d\-\n]{0,36}(-?\d+(?:\.\d+)?)",
    }
    values = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            value = float(match.group(1).replace(",", ""))
            values[key] = -value if key == "elasticity" and value > 0 else value
    return values


@router.post("/cases/{case_id}/messages")
async def case_message(case_id: str, body: MessageRequest, user: dict = Depends(current_user)):
    case = owned_case(case_id, user)
    message = body.content.strip()
    if not message or len(message) > 2000:
        raise HTTPException(422, "Message must contain 1–2,000 characters")
    run = store.get_run(body.run_id) if body.run_id else store.latest_completed_run(case_id)
    if not run or run["case_id"] != case_id or run["status"] != "completed":
        raise HTTPException(409, "Complete a decision run before discussing its results")
    store.add_message(case_id, run["id"], "user", message)
    overrides = _scenario_parameters(message)
    if overrides:
        answer = f"Proposed scenario for run {run['version']}: " + ", ".join(f"{k} = {v:g}" for k, v in overrides.items()) + ". Confirm to create a new run."
        store.add_message(case_id, run["id"], "assistant", answer)
        store.append_event(case_id, {"type": "scenario_proposed", "stage": "conversation",
                                      "status": "waiting", "overrides": overrides,
                                      "base_run_id": run["id"]}, run["id"])
        return {"type": "scenario_proposal", "content": answer,
                "overrides": overrides, "base_run_id": run["id"]}
    result = run["result"]
    evidence = [{"id": ev.get("id"), "excerpt": ev.get("excerpt", ""),
                 "source_type": ev.get("source_type", "unknown")}
                for ev in result.get("evidence", [])]
    try:
        llm = get_llm_provider()
        response = await llm.complete_json(
            system=("Explain an existing decision run. Use only the provided result and evidence. "
                    "Do not invent numbers or sources. Return JSON with answer and evidence_ids."),
            user=json.dumps({"question": message, "run_id": run["id"], "run_version": run["version"],
                             "decision": result, "evidence": evidence,
                             "recent_messages": case["messages"][-6:]}, default=str),
        )
        valid = {ev["id"] for ev in evidence}
        cited = [eid for eid in response.get("evidence_ids", []) if eid in valid]
        answer = str(response.get("answer") or "The current run does not contain enough information to answer that.")
        if cited:
            answer += "\n\nEvidence: " + ", ".join(f"[{eid}]" for eid in cited)
        answer += f"\n\nRun {run['version']} · {run['id']}"
    except Exception:
        answer = "The discussion model is unavailable. The saved result and evidence remain accessible in this case."
    answer += f"\n\nRun {run['version']} · {run['id']}" if "Run " not in answer else ""
    store.add_message(case_id, run["id"], "assistant", answer)
    return {"type": "answer", "content": answer, "run_id": run["id"]}


async def _execute_scenario(case_id: str, run_id: str, base_run: dict, overrides: dict):
    try:
        twin = DigitalTwin(**base_run["twin"])
        twin.primary_product().attributes.update(overrides)
        state = {"twin": twin.model_dump(), "question": twin.question,
                 "iteration": base_run["version"] + 1, "llm_calls": 0}
        simulation = await simulation_node(state)
        for event in simulation.get("events", []):
            store.append_event(case_id, {**event, "stage": "scenario_simulation"}, run_id)
        store.append_event(case_id, {"type": "stage_record", "stage": "scenario_simulation",
                                      "status": "completed", "model_or_tool": "NumPy · 5,000 draws",
                                      "state_change": {key: {"from": base_run["assumptions"].get(key), "to": value}
                                                       for key, value in overrides.items()},
                                      "input_refs": [f"run:{base_run['id']}"],
                                      "output_refs": [f"simulation:{s['id']}" for s in
                                                      simulation["twin"].get("simulations", [])[-len(twin.current_hypotheses()):]]}, run_id)
        state.update({"twin": simulation["twin"], "llm_calls": 0})
        decision = await decision_node(state)
        approved = {**base_run["assumptions"], **overrides}
        result = _complete_result(decision["final_decision"], decision["twin"], approved)
        result["source_version"] = base_run["result"].get("source_version")
        store.update_run(run_id, status="completed", result=result,
                         twin=decision["twin"], assumptions=approved)
        store.update_case(case_id, status="completed")
        store.append_event(case_id, {"type": "case_completed", "stage": "scenario_decision",
                                      "status": "completed", "run_id": run_id}, run_id)
    except Exception as exc:
        store.update_run(run_id, status="failed", result={"error": str(exc)})
        store.update_case(case_id, status="completed")
        store.append_event(case_id, {"type": "error", "stage": "scenario",
                                      "status": "failed", "message": str(exc)}, run_id)


@router.post("/cases/{case_id}/runs", status_code=201)
async def confirm_scenario(case_id: str, body: ScenarioRequest, user: dict = Depends(current_user)):
    case = owned_case(case_id, user)
    if case["status"] != "completed":
        raise HTTPException(409, "Finish the current case before creating another run")
    base = store.get_run(body.base_run_id)
    if not base or base["case_id"] != case_id or base["status"] != "completed" or not base["twin"]:
        raise HTTPException(404, "Base run not available")
    if not body.overrides or set(body.overrides) - {"cac_inr", "elasticity"}:
        raise HTTPException(422, "Only CAC and elasticity scenarios are supported")
    if any(not math.isfinite(value) for value in body.overrides.values()) or body.overrides.get("cac_inr", 0) < 0 or body.overrides.get("elasticity", -1) >= 0:
        raise HTTPException(422, "CAC must be nonnegative and elasticity negative")
    run = store.add_run(case_id, "running", assumptions={**base["assumptions"], **body.overrides})
    store.update_case(case_id, status="running")
    store.append_event(case_id, {"type": "scenario_confirmed", "stage": "scenario",
                                  "status": "running", "base_run_id": base["id"],
                                  "overrides": body.overrides, "reviewed_by": user["id"]}, run["id"])
    _dispatch(_execute_scenario(case_id, run["id"], base, body.overrides))
    return run


def _export_payload(case: dict, selected_run: dict) -> dict:
    result = selected_run["result"]
    return {
        "case": {"id": case["id"], "question": case["question"],
                 "source_snapshot": case["source_snapshot"], "documents": case["documents"]},
        "run": selected_run, "run_versions": case["runs"],
        "events": case["events"], "messages": case["messages"],
        "fixture_data_present": any(ev.get("source_type") == "fixture"
                                    for ev in result.get("evidence", [])),
    }


def _pdf_bytes(payload: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from urllib.parse import urlsplit

    output = io.BytesIO()
    report = SimpleDocTemplate(output, pagesize=A4, leftMargin=46, rightMargin=46,
                               topMargin=46, bottomMargin=46)
    font_roots = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    font_candidates = [
        (font_roots[0] / "arial.ttf", font_roots[0] / "arialbd.ttf"),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    ]
    font_pair = next(((normal, bold) for normal, bold in font_candidates if normal.exists() and bold.exists()), None)
    if font_pair:
        normal_font, bold_font = "StrategyTwinSans", "StrategyTwinSans-Bold"
        registered = pdfmetrics.getRegisteredFontNames()
        if normal_font not in registered:
            pdfmetrics.registerFont(TTFont(normal_font, str(font_pair[0])))
        if bold_font not in registered:
            pdfmetrics.registerFont(TTFont(bold_font, str(font_pair[1])))
        pdfmetrics.registerFontFamily(normal_font, normal=normal_font, bold=bold_font,
                                      italic=normal_font, boldItalic=bold_font)
    else:
        normal_font, bold_font = "Helvetica", "Helvetica-Bold"
    styles = getSampleStyleSheet()
    styles["Heading2"].fontName = bold_font
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontName=bold_font,
                              fontSize=22, leading=25, textColor=colors.HexColor("#292a27"), alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="ReportBody", parent=styles["BodyText"], fontSize=9,
                              fontName=normal_font, leading=12, spaceAfter=6, textColor=colors.HexColor("#292a27")))
    styles.add(ParagraphStyle(name="ReportSmall", parent=styles["BodyText"], fontSize=7,
                              fontName=normal_font, leading=9, textColor=colors.HexColor("#686c65")))
    case, run = payload["case"], payload["run"]
    result = run["result"]
    story = [Paragraph("STRATEGY TWIN / DECISION FILE", styles["ReportSmall"]), Spacer(1, 12),
             Paragraph(escape(case["question"] or "Decision report"), styles["ReportTitle"]),
             Paragraph(f"Decision run {run['version']}", styles["ReportSmall"]),
             Spacer(1, 16), Paragraph("Recommendation", styles["Heading2"]),
             Paragraph(escape(str(result.get("recommendation") or "No recommendation")), styles["ReportBody"]),
             Paragraph(escape(str(result.get("rationale") or "")), styles["ReportBody"])]
    if payload["fixture_data_present"]:
        story.append(Paragraph("FIXTURE / DEMO DATA — external evidence is illustrative.", styles["ReportBody"]))
    if result.get("simulations"):
        story.append(Paragraph("Projected monthly outcomes", styles["Heading2"]))
        rows = [["Option", "Mean", "P10", "P50", "P90", "P(profit)"]]
        hypothesis_titles = {item.get("id"): item.get("title") for item in result.get("hypotheses", [])}
        for sim in result["simulations"]:
            option = hypothesis_titles.get(sim.get("hypothesis_id")) or sim.get("channel") or "Option"
            rows.append([escape(str(option)), *[f"₹{sim.get(key, 0):,.0f}" for key in
                         ("avg_profit", "p10_profit", "p50_profit", "p90_profit")],
                         f"{100 * sim.get('prob_positive', 0):.1f}%"])
        table = Table(rows, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e3d8")),
                                   ("LINEBELOW", (0, 0), (-1, -1), .4, colors.HexColor("#c8c5bb")),
                                   ("FONTNAME", (0, 0), (-1, -1), normal_font),
                                   ("FONTSIZE", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
        story.extend([table, Spacer(1, 14)])
    for heading, key in (("Approved assumptions", "key_assumptions"),
                         ("What could change the decision", "what_would_change"),
                         ("Open questions", "open_questions")):
        values = result.get(key) or []
        if values:
            story.append(Paragraph(heading, styles["Heading2"]))
            story.extend(Paragraph("• " + escape(str(value)), styles["ReportBody"]) for value in values)
    if result.get("pilot"):
        pilot = result["pilot"]
        story.append(Paragraph("Capped pilot", styles["Heading2"]))
        story.append(Paragraph(f"Duration: {pilot.get('duration_weeks', '—')} weeks", styles["ReportBody"]))
        if pilot.get("budget_cap_inr") is not None:
            story.append(Paragraph(f"Budget cap: ₹{pilot['budget_cap_inr']:,.0f}", styles["ReportBody"]))
        if pilot.get("measure"):
            story.append(Paragraph(f"Measure: {escape(', '.join(map(str, pilot['measure'])))}", styles["ReportBody"]))
        if pilot.get("stop_condition"):
            story.append(Paragraph(f"Stop condition: {escape(str(pilot['stop_condition']))}", styles["ReportBody"]))
    if result.get("evidence"):
        story.append(Paragraph("Evidence and provenance", styles["Heading2"]))
        for ev in result["evidence"]:
            source = str(ev.get("source") or "")
            parsed_source = urlsplit(source)
            if parsed_source.scheme in {"http", "https"} and parsed_source.hostname:
                host = parsed_source.hostname.lower().removeprefix("www.")
                source_names = {"cnbc.com": "CNBC", "finance.yahoo.com": "Yahoo Finance",
                                "yahoo.com": "Yahoo", "futuremarketinsights.com": "Future Market Insights",
                                "factmr.com": "Fact.MR"}
                label = source_names.get(host, host)
                source_markup = f'<link href="{escape(source, quote=True)}" color="#355b53">{escape(label)}</link>'
            else:
                source_markup = escape("Company document" if source.startswith("document:") else source or "Source")
            source_type = escape(str(ev.get("source_type") or "source").replace("_", " ").title())
            excerpt = escape(str(ev.get("excerpt") or ""))
            story.append(Paragraph(f"{source_markup} - {source_type}: {excerpt}", styles["ReportSmall"]))
    report.build(story)
    return output.getvalue()


@router.get("/cases/{case_id}/exports/{format_name}")
def export_case(case_id: str, format_name: str, run_id: str | None = None,
                user: dict = Depends(current_user)):
    case = owned_case(case_id, user)
    run = store.get_run(run_id) if run_id else store.latest_completed_run(case_id)
    if not run or run["case_id"] != case_id or run["status"] != "completed":
        raise HTTPException(404, "Completed run not found")
    payload = _export_payload(case, run)
    filename = f"strategy-twin-{case_id[:8]}-run-{run['version']}"
    if format_name == "json":
        return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{filename}.json"'})
    if format_name == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["record_type", "id", "value", "avg_profit", "p10_profit", "p50_profit", "p90_profit", "prob_positive", "run_id", "fixture_data"])
        for sim in run["result"].get("simulations", []):
            writer.writerow(["projection", sim.get("hypothesis_id"), "", *(sim.get(k, "") for k in
                             ("avg_profit", "p10_profit", "p50_profit", "p90_profit", "prob_positive")),
                             run["id"], payload["fixture_data_present"]])
        for key, value in run["assumptions"].items():
            writer.writerow(["approved_assumption", key, value, "", "", "", "", "", run["id"], payload["fixture_data_present"]])
        return Response(output.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'})
    if format_name == "pdf":
        return Response(_pdf_bytes(payload), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'})
    raise HTTPException(404, "Choose PDF, CSV or JSON")
