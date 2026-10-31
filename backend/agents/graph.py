"""
LangGraph Orchestration — the actual agentic state machine.

Graph structure:
  START
    → understand        (extract business entities from document)
    → planner           (identify gaps, create research tasks)
    → research          (execute one research task)
    ↓  (loop if more tasks remain and limits not hit)
    → strategy          (generate competing hypotheses)
    → simulate          (Monte Carlo simulation for all hypotheses)
    → devil             (adversarial challenge of leading hypothesis)
    ↓  (branch: if critical weakness found → replan + more research)
    → decision          (synthesize final recommendation)
    → END

Key behaviors:
- The graph can loop through research → strategy → simulate → devil multiple times
- Branching is based on real state (remaining tasks, iteration budget, adversarial findings)
- Each node mutates the shared state
- All events are streamed to the UI in real-time
"""
from __future__ import annotations
import asyncio
import logging
import math
from typing import Literal

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agents.state import CaseRunState
from agents.understand import understand_node
from agents.planner import planner_node
from agents.research import research_node
from agents.strategy import strategy_node
from agents.simulate import simulation_node
from agents.devil import devil_node
from agents.decision import decision_node
from config import settings
from workspace_store import DB_PATH
from twin import DigitalTwin, Evidence, EpistemicStatus, to_float

logger = logging.getLogger(__name__)


# ── Conditional edge functions ────────────────────────────────────────────────

def should_research(state: CaseRunState) -> Literal["research", "strategy"]:
    """After planning: do we have research tasks and budget remaining?"""
    tasks = state.get("research_tasks", [])
    calls = state.get("research_calls", 0)
    max_calls = state.get("max_research_calls", settings.max_research_calls)
    if tasks and calls < max_calls:
        return "research"
    return "strategy"


def research_loop(state: CaseRunState) -> Literal["research", "strategy"]:
    """After a research cycle: continue or move to strategy?"""
    tasks = state.get("research_tasks", [])
    calls = state.get("research_calls", 0)
    max_calls = state.get("max_research_calls", settings.max_research_calls)
    iterations = state.get("iteration", 0)
    max_iter = state.get("max_iterations", settings.max_iterations)

    if tasks and calls < max_calls and iterations < max_iter:
        return "research"
    return "strategy"


def devil_outcome(state: CaseRunState) -> Literal["replan", "decision"]:
    """After Devil's Advocate: replan (more research) or go straight to decision?"""
    triggered = state.get("adversarial_triggered_replan", False)
    tasks = state.get("research_tasks", [])
    iterations = state.get("iteration", 0)
    max_iter = state.get("max_iterations", settings.max_iterations)
    calls = state.get("research_calls", 0)
    max_calls = state.get("max_research_calls", settings.max_research_calls)

    # Replan only if: adversarial found critical weakness AND we have budget to research it.
    # (Without research budget a replan would just re-simulate identical inputs.)
    if triggered and tasks and iterations < max_iter - 2 and calls < max_calls:
        return "replan"
    return "decision"


def replan_route(state: CaseRunState) -> Literal["research", "simulate"]:
    """After replan: run new research tasks or go back to simulate?"""
    tasks = state.get("research_tasks", [])
    calls = state.get("research_calls", 0)
    max_calls = state.get("max_research_calls", settings.max_research_calls)
    if tasks and calls < max_calls:
        return "research"
    return "simulate"


# ── Node wrappers (increment iteration counter) ───────────────────────────────

async def _wrap_understand(state: CaseRunState) -> dict:
    result = await understand_node(state)
    corrections = state.get("source_corrections", [])
    if corrections and result.get("twin"):
        twin = DigitalTwin(**result["twin"])
        entities = (twin.companies + twin.products + twin.segments + twin.competitors +
                    twin.markets + twin.constraints + twin.objectives)
        for correction in corrections:
            target = next((item for item in entities if item.type == correction["entity_type"]
                           and item.name.casefold() == correction["entity_name"].casefold()), None)
            if target:
                target.attributes[correction["field"]] = correction["value"]
                target.epistemic[correction["field"]] = EpistemicStatus.KNOWN
                twin.add_evidence(Evidence(source="user correction", source_type="internal",
                    excerpt=f"{target.name} · {correction['field']}: {correction['value']}",
                    epistemic=EpistemicStatus.KNOWN))
                result.setdefault("events", []).append({"type": "source_correction_applied",
                    "entity": target.name, "field": correction["field"],
                    "message": f"Applied owner correction to {target.name}."})
            else:
                result.setdefault("events", []).append({"type": "source_correction_unmatched",
                    "entity": correction["entity_name"], "field": correction["field"],
                    "message": "A source correction could not be matched in this extraction."})
        result["twin"] = twin.model_dump()
    result["iteration"] = state.get("iteration", 0)
    return result


async def _wrap_planner(state: CaseRunState) -> dict:
    result = await planner_node(state)
    result["iteration"] = state.get("iteration", 0) + 1
    result["adversarial_triggered_replan"] = False  # reset
    return result


async def _wrap_research(state: CaseRunState) -> dict:
    result = await research_node(state)
    return result


async def _wrap_strategy(state: CaseRunState) -> dict:
    result = await strategy_node(state)
    return result


async def _wrap_simulate(state: CaseRunState) -> dict:
    result = await simulation_node(state)
    return result


async def _wrap_devil(state: CaseRunState) -> dict:
    result = await devil_node(state)
    return result


async def _wrap_replan(state: CaseRunState) -> dict:
    """Replan after adversarial challenge — call planner again with adversarial context."""
    adversarial_tasks = state.get("research_tasks", [])   # queued by Devil's Advocate
    result = await planner_node(state)
    # Keep the Devil's Advocate tasks first, then add new planner tasks (deduped by query)
    seen = set()
    merged = []
    for t in adversarial_tasks + result.get("research_tasks", []):
        q = str(t.get("query", "")).strip().lower()
        if q and q not in seen:
            seen.add(q)
            merged.append(t)
    result["research_tasks"] = merged
    result["iteration"] = state.get("iteration", 0) + 1
    result["adversarial_triggered_replan"] = False
    return result


async def _wrap_decision(state: CaseRunState) -> dict:
    result = await decision_node(state)
    return result


def _review_values(twin: DigitalTwin) -> dict:
    attrs = twin.primary_product().attributes
    cash = to_float(attrs.get("cash_available_inr"), None)
    pilot_cap = min(25000.0, cash * 0.1) if cash is not None else 25000.0
    return {key: to_float(attrs.get(key), default) for key, default in {
        "base_demand": 1000.0, "elasticity": -1.2, "cac_inr": 300.0,
        "unit_cost_inr": 200.0, "fixed_cost_inr": 50000.0,
        "pilot_budget_cap_inr": pilot_cap,
    }.items()}


async def _approval_node(state: CaseRunState) -> dict:
    twin = DigitalTwin(**state["twin"])
    current = _review_values(twin)
    answer = interrupt({"type": "assumption_review", "values": current,
                        "message": "Review consequential assumptions before the final simulation."})
    if not isinstance(answer, dict) or answer.get("approved") is not True:
        return {"approval": {"approved": False}, "stop_reason": "assumptions_rejected",
                "events": [{"type": "approval_rejected", "stage": "approval",
                            "message": "Assumptions were not approved."}]}
    values = answer.get("values") or current
    if set(values) != set(current):
        raise ValueError("Approval values must contain exactly the reviewed parameters")
    normalized = {key: float(value) for key, value in values.items()}
    if any(not math.isfinite(value) for value in normalized.values()):
        raise ValueError("Approval values must be finite")
    if any(normalized[key] < 0 for key in ("base_demand", "cac_inr", "unit_cost_inr", "fixed_cost_inr", "pilot_budget_cap_inr")):
        raise ValueError("Costs and demand cannot be negative")
    if normalized["elasticity"] >= 0:
        raise ValueError("Price elasticity must be negative")
    twin.primary_product().attributes.update(normalized)
    changes = {key: {"from": old, "to": normalized[key]} for key, old in current.items()
               if normalized[key] != old}
    return {"twin": twin.model_dump(), "approval": {"approved": True, "values": normalized,
            "reviewed_by": answer.get("reviewed_by"), "changes": changes},
            "events": [{"type": "assumptions_approved", "stage": "approval", "values": normalized,
                        "changes": changes, "message": "Assumptions approved for final simulation."}]}


async def _final_simulation_node(state: CaseRunState) -> dict:
    result = await simulation_node({**state, "iteration": state.get("iteration", 0) + 1})
    result["iteration"] = state.get("iteration", 0) + 1
    result["events"] = [{"type": "final_simulation_started", "stage": "final_simulation",
                         "message": "Running final simulation with approved assumptions."}] + result.get("events", [])
    return result


# ── Build the graph ───────────────────────────────────────────────────────────

def build_graph(require_approval: bool = False, checkpointer=None) -> StateGraph:
    builder = StateGraph(CaseRunState)

    # Add nodes
    builder.add_node("understand", _wrap_understand)
    builder.add_node("planner", _wrap_planner)
    builder.add_node("research", _wrap_research)
    builder.add_node("strategy", _wrap_strategy)
    builder.add_node("simulate", _wrap_simulate)
    builder.add_node("devil", _wrap_devil)
    builder.add_node("replan", _wrap_replan)
    builder.add_node("decision", _wrap_decision)
    if require_approval:
        builder.add_node("approval", _approval_node)
        builder.add_node("final_simulation", _final_simulation_node)

    # Edges
    builder.add_edge(START, "understand")
    builder.add_edge("understand", "planner")

    # After planner: research if tasks, else strategy
    builder.add_conditional_edges(
        "planner",
        should_research,
        {"research": "research", "strategy": "strategy"},
    )

    # After research: loop or strategy
    builder.add_conditional_edges(
        "research",
        research_loop,
        {"research": "research", "strategy": "strategy"},
    )

    # Strategy → simulate → devil
    builder.add_edge("strategy", "simulate")
    builder.add_edge("simulate", "devil")

    # After devil: replan or decision
    builder.add_conditional_edges(
        "devil",
        devil_outcome,
        {"replan": "replan", "decision": "approval" if require_approval else "decision"},
    )

    # After replan: more research or re-simulate
    builder.add_conditional_edges(
        "replan",
        replan_route,
        {"research": "research", "simulate": "simulate"},
    )

    # After additional research triggered by adversarial: re-simulate
    # (This path: research → strategy → simulate → devil → replan → research → simulate)
    # The research_loop handles whether to loop or go to strategy.
    # When coming back to strategy after adversarial replan, strategy may add hypotheses.

    if require_approval:
        builder.add_conditional_edges("approval", lambda state: "final_simulation" if (state.get("approval") or {}).get("approved") else "end",
                                      {"final_simulation": "final_simulation", "end": END})
        builder.add_edge("final_simulation", "decision")
    builder.add_edge("decision", END)

    return builder.compile(checkpointer=checkpointer)


# ── Run the workflow ──────────────────────────────────────────────────────────

async def run_case(
    case_id: str,
    question: str,
    doc_id: str | None,
    event_callback,   # async callable(event: dict)
    require_approval: bool = False,
    resume: dict | None = None,
    checkpoint_id: str | None = None,
    source_corrections: list[dict] | None = None,
    source_document_ids: list[str] | None = None,
    prebuilt_twin: dict | None = None,
) -> dict:
    """
    Run the full agentic workflow for a case.
    Calls event_callback for each event produced by agents (for SSE streaming).
    Returns the final decision package.
    """
    initial_state: CaseRunState = {
        "case_id": case_id,
        "question": question,
        "doc_id": doc_id,
        "twin": prebuilt_twin,   # None → understand_node runs; dict → understand_node skips LLM
        "iteration": 0,
        "research_calls": 0,
        "llm_calls": 0,
        "max_iterations": settings.max_iterations,
        "max_research_calls": settings.max_research_calls,
        "unknowns": [],
        "research_tasks": [],
        "completed_tasks": [],
        "evidence_summaries": [],
        "events": [],
        "needs_more_research": False,
        "adversarial_triggered_replan": False,
        "is_done": False,
        "stop_reason": None,
        "final_decision": None,
        "approval": None,
        "source_corrections": source_corrections or [],
        "messages": [],
    }

    async def execute(graph, graph_input, config):
        final_state = dict(initial_state)
        interrupted = None
        try:
            async for chunk in graph.astream(graph_input, stream_mode="updates", config=config):
                for node_name, node_output in chunk.items():
                    if node_name == "__interrupt__":
                        interrupted = node_output
                        continue
                    if not node_output or not isinstance(node_output, dict):
                        continue
                    previous = final_state.get("twin") or {}
                    updated = node_output.get("twin") or previous
                    previous_evidence = {item["id"] for item in previous.get("evidence", [])}
                    added_evidence = [item for item in updated.get("evidence", []) if item["id"] not in previous_evidence]
                    record = {
                        "type": "stage_record", "stage": node_name, "status": "completed",
                        "input_refs": ([f"document:{item}" for item in (source_document_ids or ([doc_id] if doc_id else []))]
                                       if node_name == "understand" else []) +
                                      ([f"evidence:{item['id']}" for item in previous.get("evidence", [])[-8:]] if node_name in {"strategy", "decision"} else []),
                        "output_refs": [f"evidence:{item['id']}" for item in added_evidence],
                        "evidence_ids": [item["id"] for item in added_evidence],
                        "is_fixture": any(item.get("source_type") == "fixture" for item in added_evidence),
                        "model_or_tool": "NumPy · 5,000 draws" if "simulat" in node_name else
                                         ("LangGraph route" if node_name in {"replan", "approval"} else settings.llm_model),
                    }
                    if node_name in {"simulate", "final_simulation"}:
                        old_sims = previous.get("simulations", [])
                        new_sims = updated.get("simulations", [])
                        if new_sims:
                            current = max(new_sims[len(old_sims):] or new_sims, key=lambda s: s["avg_profit"])
                            before = max(old_sims, key=lambda s: s["avg_profit"]) if old_sims else None
                            record["state_change"] = {"leading_hypothesis_id": {
                                "from": before["hypothesis_id"] if before else None,
                                "to": current["hypothesis_id"]},
                                "expected_profit_inr": {"from": before["avg_profit"] if before else None,
                                                         "to": current["avg_profit"]}}
                            record["output_refs"].extend(f"simulation:{s['id']}" for s in new_sims[len(old_sims):])
                    if node_name == "devil":
                        previous_challenges = {item["id"] for item in previous.get("challenges", [])}
                        added_challenges = [item for item in updated.get("challenges", [])
                                            if item["id"] not in previous_challenges]
                        record["output_refs"].extend(f"challenge:{item['id']}" for item in added_challenges)
                        record["state_change"] = {"challenges_added": [
                            {"id": item["id"], "assumption": item.get("assumption_targeted"),
                             "severity": item.get("severity")} for item in added_challenges],
                            "replan_triggered": node_output.get("adversarial_triggered_replan", False)}
                    if node_name == "replan":
                        record["state_change"] = {"research_tasks": [task.get("query") for task in
                                                    node_output.get("research_tasks", [])]}
                    if node_name == "approval":
                        record["state_change"] = node_output.get("approval", {}).get("changes", {})
                    await event_callback(record)
                    if node_name == "understand" and updated:
                        await event_callback({"type": "source_twin_extracted", "stage": "understand",
                                              "status": "completed", "twin": updated,
                                              "used_passages": next((event.get("used_passages", []) for event in
                                                  node_output.get("events", []) if event.get("type") == "agent_complete"), [])})
                    for event in node_output.get("events", []):
                        await event_callback({**event, "node": node_name})
                    final_state.update({k: v for k, v in node_output.items() if k != "events"})
        except Exception as e:
            logger.error("Graph execution error: %s", e, exc_info=True)
            await event_callback({"type": "error", "message": f"Workflow error: {e}", "node": "graph"})
            return {"error": str(e), "status": "failed"}
        if interrupted:
            payload = interrupted[0].value if isinstance(interrupted, (tuple, list)) else interrupted
            await event_callback({"type": "approval_required", "stage": "approval", "status": "waiting",
                                  "approval": payload})
            return {"status": "awaiting_approval", "approval": payload, "twin": final_state.get("twin")}
        if (final_state.get("approval") or {}).get("approved") is False:
            return {"status": "rejected", "twin": final_state.get("twin")}
        return {"status": "completed", "result": final_state.get("final_decision"),
                "twin": final_state.get("twin"), "approval": final_state.get("approval")}

    graph_input = Command(resume=resume) if resume is not None else initial_state
    config = {"recursion_limit": 100, "configurable": {"thread_id": checkpoint_id or case_id}}
    if require_approval:
        checkpoint_path = DB_PATH.with_name("graph-checkpoints.sqlite3")
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            outcome = await execute(build_graph(True, saver), graph_input, config)
    else:
        outcome = await execute(build_graph(), graph_input, config)
    return outcome if require_approval else outcome.get("result") or {"error": outcome.get("error", "No final decision produced")}
