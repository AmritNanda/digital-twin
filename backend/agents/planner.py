"""
Planner Agent — Node 2 in the LangGraph.

Responsibilities:
- Examine the current Digital Twin state
- Identify which unknowns are decision-critical
- Generate specific, targeted research tasks
- Prioritize tasks by expected information value

The planner is dynamic — it adapts based on what is already known
and what the most impactful gap is for the current strategic question.
"""
from __future__ import annotations
import logging
from twin import DigitalTwin
from providers.llm import get_llm_provider, LLMUnavailableError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a strategic research planner for a decision intelligence system.

Your job is to examine the current state of knowledge about a company and its market,
identify the most critical information gaps for the strategic question,
and produce a prioritized list of specific research tasks.

Rules:
1. Only create research tasks for things that are genuinely UNKNOWN or UNCERTAIN
2. Each task must be specific enough that an internet search could yield useful results
3. Prioritize by decision impact — what would most change the recommendation?
4. Return at most 2 tasks — the two highest-priority unknowns only
5. Do not create duplicate tasks for things already in the completed list
6. Consider: price sensitivity, competitor positioning, market size, regulatory requirements,
   customer acquisition costs, distribution channels, and financial feasibility
"""

PLAN_PROMPT = """Current Digital Twin State:
{twin_context}

Strategic Question: {question}

Already investigated:
{completed_tasks}

Known unknowns identified earlier:
{unknowns}

What are the MOST CRITICAL information gaps for answering this question?
Produce a JSON with:
{{
  "research_tasks": [
    {{
      "query": "specific search query to fill this gap",
      "topic": "price_sensitivity | competitor | market_size | regulatory | cac | distribution | other",
      "reason": "why this is decision-critical",
      "priority": 1
    }}
  ],
  "planning_rationale": "brief explanation of the planning strategy"
}}

Order tasks by priority (1 = most important).
"""


async def planner_node(state: dict) -> dict:
    """LangGraph node: determine what research is needed next."""
    import time
    t0 = time.perf_counter()

    twin_data = state.get("twin", {})
    twin = DigitalTwin(**twin_data) if twin_data else None

    question = state["question"]
    completed = state.get("completed_tasks", [])
    unknowns = state.get("unknowns", [])
    llm = get_llm_provider()

    # Cap context sent to the model: key entities + up to 5 unknowns only
    if twin:
        context_lines = twin.to_context_str().splitlines()
        twin_context = "\n".join(context_lines[:80])  # ~2 000 tokens max
    else:
        twin_context = f"Question: {question}"

    events = [{
        "type": "agent_start",
        "agent": "Planner Agent",
        "message": "Evaluating what evidence is needed to answer the strategic question...",
        "iteration": state.get("iteration", 0),
    }]

    try:
        result = await llm.complete_json(
            system=SYSTEM_PROMPT,
            user=PLAN_PROMPT.format(
                twin_context=twin_context,
                question=question,
                completed_tasks="\n".join(f"- {t}" for t in completed) or "None yet",
                unknowns="\n".join(f"- {u}" for u in unknowns[:5]) or "None identified",
            ),
        )
    except LLMUnavailableError:
        raise
    except Exception as e:
        logger.error(f"Planner LLM error: {e}")
        result = {"research_tasks": [], "planning_rationale": ""}

    elapsed = time.perf_counter() - t0
    logger.info("[TIMING] planner_node: %.2fs", elapsed)

    # Keep only well-formed tasks that haven't already been investigated.
    # Limit to 2 tasks per cycle — we prefer fewer, higher-value searches.
    done = {c.split(":")[0].strip().lower() for c in completed}
    tasks = [
        t for t in (result.get("research_tasks") or [])
        if isinstance(t, dict) and t.get("query") and t["query"].strip().lower() not in done
    ][:2]
    rationale = result.get("planning_rationale", "")

    events.append({
        "type": "agent_complete",
        "agent": "Planner Agent",
        "message": f"Generated {len(tasks)} research tasks in {elapsed:.1f}s. Strategy: {rationale}",
        "research_tasks": tasks,
        "elapsed_seconds": round(elapsed, 2),
    })

    return {
        "research_tasks": tasks,
        "llm_calls": state.get("llm_calls", 0) + 1,
        "events": events,
    }
