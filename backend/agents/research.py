"""
Research Agent — Node 3 in the LangGraph.

Responsibilities:
- Execute research tasks from the planner
- Search external sources (Tavily / demo fixtures)
- Interpret results using LLM reasoning
- Ingest evidence into the RAG store
- Update the Digital Twin with discovered entities/facts
- Detect contradictions with existing evidence
"""
from __future__ import annotations
import asyncio
import logging
from twin import DigitalTwin, Evidence, EpistemicStatus, Competitor, Market, to_float, to_str_list
from providers.llm import get_llm_provider, LLMUnavailableError
from providers.search import get_search_provider
from rag.ingest import ingest_text

logger = logging.getLogger(__name__)

INTERPRET_SYSTEM = """You are a strategic evidence analyst.
You have received web search results related to a specific strategic research question.

Your job is to:
1. Extract the most relevant facts and insights from the search results
2. Assess the quality and reliability of each source
3. Identify any contradictions with stated company information
4. Update the business model with new entities or data points if discovered
5. Produce a concise evidence summary

Be critical. Not all search results are high quality. Note when sources are:
- Marketing content (biased)
- Opinion (not data)
- Outdated
- Geographically wrong
- Conflicting with each other

Mark epistemic status:
- "known" = directly stated data with a credible source
- "inferred" = deduced from context
- "assumed" = general industry assumption
"""

INTERPRET_PROMPT = """Research Query: {query}

Search Results:
{results}

Current company knowledge:
{twin_context}

Analyse these search results and produce a JSON response:
{{
  "evidence_items": [
    {{
      "excerpt": "specific fact or data point extracted",
      "source_url": "url",
      "source_type": "web|news|fixture",
      "epistemic": "known|inferred|assumed",
      "tags": ["price", "competitor", "demand", etc],
      "quality": "high|medium|low",
      "quality_reason": "why this quality rating"
    }}
  ],
  "new_entities": {{
    "competitors": [{{"name": "...", "price_inr": null, "channel": "...", "attributes": {{}}}}],
    "segments": [{{"name": "...", "description": "...", "attributes": {{}}}}],
    "markets": [{{"name": "...", "size_inr_crore": null, "growth_pct": null, "attributes": {{}}}}]
  }},
  "parameter_updates": {{
    "elasticity": null,
    "cac_inr": null,
    "competitor_price_inr": null
  }},
  "contradictions": ["description of any contradiction found"],
  "bias_warnings": ["source concentration issue, geographic skew, etc."],
  "research_summary": "concise 2-sentence summary of what was learned"
}}
"""


async def research_node(state: dict) -> dict:
    """LangGraph node: execute one research task and update the twin."""
    tasks = state.get("research_tasks", [])
    if not tasks:
        return {"events": [{"type": "agent_skip", "agent": "Research Agent", "message": "No research tasks"}]}

    # Take the highest priority task
    task = min(tasks, key=lambda t: to_float(t.get("priority"), 99.0))
    remaining_tasks = [t for t in tasks if t is not task]

    query = task.get("query", "")
    case_id = state["case_id"]
    question = state["question"]

    twin_data = state.get("twin", {})
    twin = DigitalTwin(**twin_data) if twin_data else DigitalTwin(case_id=case_id, question=question)

    events = [{
        "type": "agent_start",
        "agent": "Research Agent",
        "message": f"Investigating: {query}",
        "query": query,
        "topic": task.get("topic", ""),
        "reason": task.get("reason", ""),
        "iteration": state.get("iteration", 0),
    }]

    # Search external sources
    search = get_search_provider()
    results = await search.search(query, max_results=5)
    is_demo = any(r.is_fixture for r in results)

    if not results:
        events.append({
            "type": "research_result",
            "agent": "Research Agent",
            "message": "No results found for this query",
            "is_demo": is_demo,
        })
        completed = state.get("completed_tasks", []) + [query]
        return {
            "research_tasks": remaining_tasks,
            "completed_tasks": completed,
            "research_calls": state.get("research_calls", 0) + 1,
            "events": events,
        }

    # Format results for LLM interpretation
    results_text = "\n\n".join(
        f"[{i+1}] {r.title}\nURL: {r.url}\n{r.snippet}"
        for i, r in enumerate(results)
    )

    llm = get_llm_provider()
    try:
        interpreted = await llm.complete_json(
            system=INTERPRET_SYSTEM,
            user=INTERPRET_PROMPT.format(
                query=query,
                results=results_text,
                twin_context=twin.to_context_str(),
            ),
        )
    except LLMUnavailableError:
        raise
    except Exception as e:
        logger.error(f"Research interpretation error: {e}")
        interpreted = {}

    # Update twin with evidence
    new_evidence_ids = []
    new_evidence = []
    for item in interpreted.get("evidence_items") or []:
        if not isinstance(item, dict) or not item.get("excerpt"):
            continue
        ev = Evidence(
            source=str(item.get("source_url") or query),
            source_type="fixture" if is_demo else str(item.get("source_type") or "web"),
            excerpt=str(item["excerpt"]),
            tags=to_str_list(item.get("tags")),
            epistemic=EpistemicStatus.parse(item.get("epistemic")),
        )
        twin.add_evidence(ev)
        new_evidence_ids.append(ev.id)
        new_evidence.append(ev.model_dump())
        # Also ingest into RAG (blocking embedding work → thread)
        await asyncio.to_thread(ingest_text, ev.excerpt, case_id, ev.source)

    # Add new entities to twin
    new_entities = interpreted.get("new_entities", {})
    for comp in new_entities.get("competitors", []):
        if comp.get("name"):
            existing_names = [c.name for c in twin.competitors]
            if comp["name"] not in existing_names:
                c = Competitor(
                    name=comp["name"],
                    attributes={k: v for k, v in comp.items() if k != "name" and v is not None},
                )
                twin.competitors.append(c)
                events.append({
                    "type": "twin_update",
                    "entity_type": "Competitor",
                    "name": c.name,
                    "attributes": c.attributes,
                    "message": f"New competitor discovered: {c.name}",
                })

    for mkt in new_entities.get("markets", []):
        if mkt.get("name"):
            m = Market(
                name=mkt["name"],
                attributes={k: v for k, v in mkt.items() if k != "name" and v is not None},
            )
            twin.markets.append(m)
            events.append({
                "type": "twin_update",
                "entity_type": "Market",
                "name": m.name,
                "attributes": m.attributes,
                "message": f"Market data discovered: {m.name}",
            })

    # Parameter updates
    param_updates = {k: v for k, v in (interpreted.get("parameter_updates") or {}).items() if v is not None}
    if param_updates:
        twin.primary_product().attributes.update(param_updates)

    # Contradictions + bias
    contradictions = to_str_list(interpreted.get("contradictions"))
    bias_warnings = to_str_list(interpreted.get("bias_warnings"))
    twin.bias_warnings.extend(b for b in bias_warnings if b not in twin.bias_warnings)

    summary = interpreted.get("research_summary", "")
    completed = state.get("completed_tasks", []) + [f"{query}: {summary}"]

    events.append({
        "type": "research_complete",
        "agent": "Research Agent",
        "message": summary or f"Gathered {len(new_evidence_ids)} evidence items",
        "evidence_count": len(new_evidence_ids),
        "new_entities": {
            "competitors": len(new_entities.get("competitors", [])),
            "markets": len(new_entities.get("markets", [])),
        },
        "contradictions": contradictions,
        "bias_warnings": bias_warnings,
        "evidence": new_evidence,
        "is_demo": is_demo,
    })

    return {
        "twin": twin.model_dump(),
        "research_tasks": remaining_tasks,
        "completed_tasks": completed,
        "research_calls": state.get("research_calls", 0) + 1,
        "llm_calls": state.get("llm_calls", 0) + 1,
        "evidence_summaries": state.get("evidence_summaries", []) + [summary],
        "events": events,
    }
