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
import time
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


# Semaphore: limit concurrent LLM interpretation calls to avoid rate limits
_INTERP_SEM = asyncio.Semaphore(3)


async def _search_and_interpret(
    task: dict,
    twin_context: str,
    case_id: str,
    is_demo_ref: list,  # mutable 1-element list so caller can read it
) -> dict:
    """Run one search + interpretation task. Returns a partial result dict."""
    query = task.get("query", "")
    search = get_search_provider()
    llm = get_llm_provider()

    t_search = time.perf_counter()
    results = await search.search(query, max_results=5)
    search_elapsed = time.perf_counter() - t_search
    is_demo = any(r.is_fixture for r in results)
    if is_demo:
        is_demo_ref[0] = True

    logger.info("[TIMING] search '%s': %.2fs, %d results", query[:60], search_elapsed, len(results))

    if not results:
        return {
            "query": query,
            "task": task,
            "interpreted": {},
            "is_demo": is_demo,
            "new_evidence": [],
            "events": [{
                "type": "research_result",
                "agent": "Research Agent",
                "message": f"No results found for: {query}",
                "is_demo": is_demo,
            }],
            "summary": "",
        }

    results_text = "\n\n".join(
        f"[{i+1}] {r.title}\nURL: {r.url}\n{r.snippet[:400]}"
        for i, r in enumerate(results)
    )

    t_interp = time.perf_counter()
    async with _INTERP_SEM:
        try:
            interpreted = await llm.complete_json(
                system=INTERPRET_SYSTEM,
                user=INTERPRET_PROMPT.format(
                    query=query,
                    results=results_text,
                    twin_context=twin_context,
                ),
            )
        except LLMUnavailableError:
            raise
        except Exception as e:
            logger.error("Research interpretation error for '%s': %s", query[:60], e)
            interpreted = {}
    interp_elapsed = time.perf_counter() - t_interp
    logger.info("[TIMING] interpret '%s': %.2fs", query[:60], interp_elapsed)

    # Build evidence objects
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
        new_evidence.append(ev)

    summary = interpreted.get("research_summary", "")
    return {
        "query": query,
        "task": task,
        "interpreted": interpreted,
        "is_demo": is_demo,
        "new_evidence": new_evidence,
        "events": [{
            "type": "research_complete",
            "agent": "Research Agent",
            "message": summary or f"Gathered {len(new_evidence)} evidence items for: {query}",
            "evidence_count": len(new_evidence),
            "is_demo": is_demo,
            "elapsed_search_s": round(search_elapsed, 2),
            "elapsed_interp_s": round(interp_elapsed, 2),
        }],
        "summary": summary,
    }


async def research_node(state: dict) -> dict:
    """LangGraph node: execute all queued research tasks concurrently, then update the twin."""
    t0 = time.perf_counter()

    tasks = state.get("research_tasks", [])
    if not tasks:
        return {"events": [{"type": "agent_skip", "agent": "Research Agent", "message": "No research tasks"}]}

    case_id = state["case_id"]
    question = state["question"]

    twin_data = state.get("twin", {})
    twin = DigitalTwin(**twin_data) if twin_data else DigitalTwin(case_id=case_id, question=question)

    # Build a slim twin context (cap at 60 lines ~1 500 tokens)
    context_lines = twin.to_context_str().splitlines()
    twin_context = "\n".join(context_lines[:60])

    events: list[dict] = [{
        "type": "agent_start",
        "agent": "Research Agent",
        "message": f"Researching {len(tasks)} task(s) concurrently...",
        "queries": [t.get("query", "") for t in tasks],
        "iteration": state.get("iteration", 0),
    }]

    is_demo_ref = [False]

    # Run all tasks concurrently
    results_list = await asyncio.gather(
        *[_search_and_interpret(task, twin_context, case_id, is_demo_ref) for task in tasks],
        return_exceptions=True,
    )

    completed = list(state.get("completed_tasks", []))
    new_evidence_ids: list[str] = []
    rag_coros = []

    for res in results_list:
        if isinstance(res, LLMUnavailableError):
            raise res
        if isinstance(res, Exception):
            logger.error("Research task error: %s", res)
            continue

        query = res["query"]
        events.extend(res["events"])
        interpreted = res["interpreted"]
        is_demo = res["is_demo"]

        for ev in res["new_evidence"]:
            twin.add_evidence(ev)
            new_evidence_ids.append(ev.id)
            rag_coros.append(asyncio.to_thread(ingest_text, ev.excerpt, case_id, ev.source))

        new_entities = interpreted.get("new_entities", {})
        for comp in new_entities.get("competitors", []):
            if comp.get("name") and comp["name"] not in [c.name for c in twin.competitors]:
                c = Competitor(
                    name=comp["name"],
                    attributes={k: v for k, v in comp.items() if k != "name" and v is not None},
                )
                twin.competitors.append(c)
                events.append({"type": "twin_update", "entity_type": "Competitor",
                                "name": c.name, "attributes": c.attributes,
                                "message": f"New competitor discovered: {c.name}"})

        for mkt in new_entities.get("markets", []):
            if mkt.get("name"):
                m = Market(
                    name=mkt["name"],
                    attributes={k: v for k, v in mkt.items() if k != "name" and v is not None},
                )
                twin.markets.append(m)
                events.append({"type": "twin_update", "entity_type": "Market",
                                "name": m.name, "attributes": m.attributes,
                                "message": f"Market data discovered: {m.name}"})

        param_updates = {k: v for k, v in (interpreted.get("parameter_updates") or {}).items() if v is not None}
        if param_updates:
            twin.primary_product().attributes.update(param_updates)

        bias_warnings = to_str_list(interpreted.get("bias_warnings"))
        twin.bias_warnings.extend(b for b in bias_warnings if b not in twin.bias_warnings)

        summary = res["summary"]
        completed.append(f"{query}: {summary}" if summary else query)

    # Fire RAG ingestion in parallel (don't block on it)
    if rag_coros:
        await asyncio.gather(*rag_coros, return_exceptions=True)

    elapsed = time.perf_counter() - t0
    logger.info("[TIMING] research_node (%d tasks): %.2fs total", len(tasks), elapsed)

    events.append({
        "type": "research_batch_complete",
        "agent": "Research Agent",
        "evidence_total": len(new_evidence_ids),
        "tasks_done": len(tasks),
        "elapsed_seconds": round(elapsed, 2),
        "is_demo": is_demo_ref[0],
    })

    return {
        "twin": twin.model_dump(),
        "research_tasks": [],           # all tasks consumed in this node
        "completed_tasks": completed,
        "research_calls": state.get("research_calls", 0) + len(tasks),
        "llm_calls": state.get("llm_calls", 0) + len(tasks),
        "evidence_summaries": state.get("evidence_summaries", []) + [r["summary"] for r in results_list if isinstance(r, dict)],
        "events": events,
    }
