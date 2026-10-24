"""
Understand Agent — Node 1 in the LangGraph.

Responsibilities:
- Parse the uploaded document text using the LLM
- Extract structured entities: Company, Product, Segments, Constraints, Objectives
- Populate the initial Digital Twin
- Identify initial unknowns / gaps
- Emit structured events for the UI
"""
from __future__ import annotations
import asyncio
import logging
import json
from twin import (
    DigitalTwin, Company, Product, CustomerSegment,
    Constraint, Objective, EpistemicStatus
)
from providers.llm import get_llm_provider, LLMUnavailableError
from rag.retriever import retrieve_for_question

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a strategic business analyst. 
Your job is to read a company document and extract structured information to build an initial Digital Twin representation.

You must identify and extract:
1. Company information (name, industry, geography, size, stage)
2. Product information (name, description, price range, channel, features)
3. Customer segments (who they are, needs, size if mentioned)
4. Competitors (if mentioned)
5. Key constraints (budget, capacity, regulatory, brand)
6. Business objectives (goals, KPIs, targets)
7. Known financial parameters (unit cost, fixed cost, revenue, margins)
8. Strategic question details (what specifically is being decided)

Then identify:
- What information is explicitly KNOWN (stated directly)
- What information is INFERRED (deduced from context)
- What information is UNKNOWN (not mentioned but needed for the decision)

Be precise. Do not invent numbers that are not in the document.
If something is not mentioned, mark it as UNKNOWN.
"""

EXTRACT_PROMPT = """Here is the company document:

---
{document_text}
---

Strategic Question: {question}

Extract all business entities and produce a JSON response with this structure:
{{
  "company": {{
    "name": "...",
    "industry": "...",
    "geography": "...",
    "stage": "early-stage|growth|established",
    "attributes": {{}}
  }},
  "product": {{
    "name": "...",
    "description": "...",
    "price_inr": null,
    "channel": "...",
    "unit_cost_inr": null,
    "attributes": {{}}
  }},
  "segments": [
    {{"name": "...", "description": "...", "size": null, "attributes": {{}}}}
  ],
  "competitors": [
    {{"name": "...", "price_inr": null, "channel": "...", "attributes": {{}}}}
  ],
  "constraints": [
    {{"name": "...", "value": "..."}}
  ],
  "objectives": [
    {{"name": "...", "target": "..."}}
  ],
  "financial_params": {{
    "base_demand": null,
    "elasticity": null,
    "unit_cost_inr": null,
    "fixed_cost_inr": null,
    "cac_inr": null,
    "cash_available_inr": null,
    "target_margin_pct": null
  }},
  "unknowns": [
    "What is the price sensitivity of the target segment?",
    "..."
  ],
  "epistemic_notes": {{
    "field_name": "known|inferred|assumed|unknown"
  }}
}}"""


async def understand_node(state: dict) -> dict:
    """LangGraph node: extract structured understanding from the document."""
    case_id = state["case_id"]
    question = state["question"]
    llm = get_llm_provider()

    events = []
    events.append({
        "type": "agent_start",
        "agent": "Understanding Agent",
        "message": "Analysing company document and extracting business entities...",
        "iteration": state.get("iteration", 0),
    })

    # Retrieve relevant chunks from RAG
    spans = await asyncio.to_thread(retrieve_for_question, question, case_id, 12)
    doc_text = "\n\n".join(s.text for s in spans) if spans else "(no document uploaded)"

    # LLM extraction
    try:
        extracted = await llm.complete_json(
            system=SYSTEM_PROMPT,
            user=EXTRACT_PROMPT.format(document_text=doc_text, question=question),
        )
    except LLMUnavailableError:
        raise
    except Exception as e:
        logger.error(f"Understand agent LLM error: {e}")
        extracted = {}

    # Build initial Digital Twin from extraction
    twin = DigitalTwin(case_id=case_id, question=question)

    company_data = extracted.get("company", {})
    if company_data.get("name"):
        co = Company(
            name=company_data["name"],
            attributes={k: v for k, v in company_data.items()
                        if k not in ("name",) and v is not None},
        )
        twin.companies.append(co)
        events.append({
            "type": "twin_update",
            "entity_type": "Company",
            "name": co.name,
            "attributes": co.attributes,
            "message": f"Company identified: {co.name}",
        })

    product_data = extracted.get("product", {})
    if product_data.get("name"):
        prod = Product(
            name=product_data["name"],
            attributes={k: v for k, v in product_data.items()
                        if k not in ("name",) and v is not None},
        )
        twin.products.append(prod)
        events.append({
            "type": "twin_update",
            "entity_type": "Product",
            "name": prod.name,
            "attributes": prod.attributes,
            "message": f"Product identified: {prod.name}",
        })

    for seg in extracted.get("segments", []):
        if seg.get("name"):
            s = CustomerSegment(name=seg["name"], attributes={k: v for k, v in seg.items() if k != "name" and v})
            twin.segments.append(s)
            events.append({
                "type": "twin_update",
                "entity_type": "CustomerSegment",
                "name": s.name,
                "message": f"Customer segment identified: {s.name}",
            })

    from twin import Competitor as CompetitorEntity
    for comp in extracted.get("competitors", []):
        if comp.get("name"):
            c = CompetitorEntity(name=comp["name"], attributes={k: v for k, v in comp.items() if k != "name" and v})
            twin.competitors.append(c)
            events.append({
                "type": "twin_update",
                "entity_type": "Competitor",
                "name": c.name,
                "attributes": c.attributes,
                "message": f"Competitor identified: {c.name}",
            })

    for cons in extracted.get("constraints", []):
        if cons.get("name"):
            cn = Constraint(name=cons["name"], attributes={"value": cons.get("value", "")})
            twin.constraints.append(cn)

    for obj in extracted.get("objectives", []):
        if obj.get("name"):
            ob = Objective(name=obj["name"], attributes={"target": obj.get("target", "")})
            twin.objectives.append(ob)

    # Store financial params in product attributes for simulation
    fp = extracted.get("financial_params") or {}
    fp = {k: v for k, v in fp.items() if v is not None}
    if fp:
        twin.primary_product().attributes.update(fp)

    # Unknowns
    unknowns = extracted.get("unknowns", [])
    twin.unknowns = unknowns

    events.append({
        "type": "agent_complete",
        "agent": "Understanding Agent",
        "summary": f"Extracted {twin.entity_summary()}. Identified {len(unknowns)} unknowns.",
        "twin_summary": twin.entity_summary(),
        "unknowns": unknowns,
        "used_passages": [{"doc_id": s.doc_id, "source": s.source,
                            "excerpt": s.text[:240], "retrieval_method": s.retrieval_method}
                           for s in spans],
    })

    return {
        "twin": twin.model_dump(),
        "unknowns": unknowns,
        "llm_calls": state.get("llm_calls", 0) + 1,
        "events": events,
        "evidence_summaries": [s.text[:200] for s in spans[:4]],
    }
