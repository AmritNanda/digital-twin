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
from typing import Literal

from langgraph.graph import StateGraph, START, END

from agents.state import CaseRunState
from agents.understand import understand_node
from agents.planner import planner_node
from agents.research import research_node
from agents.strategy import strategy_node
from agents.simulate import simulation_node
from agents.devil import devil_node
from agents.decision import decision_node
from config import settings

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


# ── Build the graph ───────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
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
        {"replan": "replan", "decision": "decision"},
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

    builder.add_edge("decision", END)

    return builder.compile()


# ── Run the workflow ──────────────────────────────────────────────────────────

async def run_case(
    case_id: str,
    question: str,
    doc_id: str | None,
    event_callback,   # async callable(event: dict)
) -> dict:
    """
    Run the full agentic workflow for a case.
    Calls event_callback for each event produced by agents (for SSE streaming).
    Returns the final decision package.
    """
    graph = build_graph()

    initial_state: CaseRunState = {
        "case_id": case_id,
        "question": question,
        "doc_id": doc_id,
        "twin": None,
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
        "messages": [],
    }

    # Accumulate node updates into a full picture of the state
    final_state = dict(initial_state)
    try:
        async for chunk in graph.astream(
            initial_state,
            stream_mode="updates",
            config={"recursion_limit": 100},
        ):
            for node_name, node_output in chunk.items():
                if not node_output:
                    continue
                events = node_output.get("events", [])
                for event in events:
                    event["node"] = node_name
                    await event_callback(event)
                final_state.update({k: v for k, v in node_output.items() if k != "events"})
    except Exception as e:
        logger.error(f"Graph execution error: {e}", exc_info=True)
        await event_callback({
            "type": "error",
            "message": f"Workflow error: {str(e)}",
            "node": "graph",
        })
        return {"error": str(e)}

    return final_state.get("final_decision") or {"error": "No final decision produced"}
