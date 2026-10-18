"""
Strategy Agent — Node 4 in the LangGraph.

Responsibilities:
- Generate competing strategic hypotheses (not one answer)
- Each hypothesis has: price, channel, segment, assumptions, expected outcome, risks
- Link hypotheses to supporting and contradicting evidence in the twin
- Use LLM reasoning to assess feasibility given constraints

The output is a set of competing Hypothesis objects in the Digital Twin.
"""
from __future__ import annotations
import asyncio
import logging
from twin import DigitalTwin, Hypothesis, to_float, to_confidence, to_str_list
from providers.llm import get_llm_provider, LLMUnavailableError
from rag.retriever import retrieve_for_question

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a strategic options analyst.

Given a company's Digital Twin (a structured representation of what is known),
your job is to generate 3–4 distinct, genuinely competing strategic hypotheses.

Each hypothesis must:
1. Be a specific, actionable strategy (not vague)
2. Include a clear price point and channel
3. Identify the primary target customer segment
4. List key assumptions it depends on
5. Describe expected outcomes in concrete terms
6. List the main risks
7. Reference any supporting evidence by excerpt keywords
8. Reference any contradicting evidence

The hypotheses should be meaningfully different from each other.
Do NOT just vary one price. Consider:
- Different price points AND channels
- Different customer segments
- Different positioning (mass market vs premium vs niche)
- Defer/pilot as a legitimate option

Be honest about uncertainty. Mark assumptions as assumptions.
"""

STRATEGY_PROMPT = """Current Digital Twin:
{twin_context}

Relevant evidence retrieved:
{evidence_context}

Strategic Question: {question}

Generate competing hypotheses as JSON:
{{
  "hypotheses": [
    {{
      "title": "short name",
      "description": "clear description of the strategy",
      "price_inr": 699,
      "channel": "d2c|retail|premium|online|pilot",
      "segment": "target customer segment name",
      "assumptions": [
        "Price elasticity is approximately -1.2",
        "CAC will remain below ₹300"
      ],
      "expected_outcome": "What success looks like in 90 days",
      "risks": [
        "Competitor X may respond with price reduction",
        "Regulatory approval may delay launch"
      ],
      "supporting_evidence_excerpts": ["excerpt keyword..."],
      "contradicting_evidence_excerpts": ["excerpt keyword..."],
      "initial_confidence": 0.65
    }}
  ],
  "strategy_rationale": "Why these are the most relevant options to compare"
}}
"""


async def strategy_node(state: dict) -> dict:
    """LangGraph node: generate competing strategic hypotheses."""
    twin_data = state.get("twin", {})
    twin = DigitalTwin(**twin_data) if twin_data else None
    question = state["question"]
    case_id = state["case_id"]
    llm = get_llm_provider()

    events = [{
        "type": "agent_start",
        "agent": "Strategy Agent",
        "message": "Generating competing strategic hypotheses...",
        "iteration": state.get("iteration", 0),
    }]

    # Retrieve relevant evidence for strategy generation
    spans = await asyncio.to_thread(retrieve_for_question, question, case_id, 8)
    evidence_context = "\n\n".join(f"[{s.source}] {s.text}" for s in spans)

    twin_context = twin.to_context_str() if twin else question

    try:
        result = await llm.complete_json(
            system=SYSTEM_PROMPT,
            user=STRATEGY_PROMPT.format(
                twin_context=twin_context,
                evidence_context=evidence_context,
                question=question,
            ),
        )
    except LLMUnavailableError:
        raise
    except Exception as e:
        logger.error(f"Strategy LLM error: {e}")
        result = {}

    hypotheses_data = [h for h in (result.get("hypotheses") or []) if isinstance(h, dict)]
    rationale = result.get("strategy_rationale", "")

    # On a re-run (after adversarial replan) the new set replaces the old one
    superseded_ids = []
    if twin and hypotheses_data:
        for old in twin.current_hypotheses():
            old.status = "superseded"
            superseded_ids.append(old.id)

    # Create Hypothesis objects and link to evidence
    created = []
    for hd in hypotheses_data:
        h = Hypothesis(
            title=str(hd.get("title") or "Unnamed"),
            description=str(hd.get("description") or ""),
            price=to_float(hd.get("price_inr")),
            channel=hd.get("channel"),
            segment=hd.get("segment"),
            assumptions=to_str_list(hd.get("assumptions")),
            risks=to_str_list(hd.get("risks")),
            expected_outcome=hd.get("expected_outcome"),
            confidence=to_confidence(hd.get("initial_confidence")),
        )
        # Link to evidence IDs by matching excerpts
        if twin:
            for ev in twin.evidence:
                for kw in to_str_list(hd.get("supporting_evidence_excerpts")):
                    if kw.lower() in ev.excerpt.lower():
                        h.supporting_evidence_ids.append(ev.id)
                for kw in to_str_list(hd.get("contradicting_evidence_excerpts")):
                    if kw.lower() in ev.excerpt.lower():
                        h.contradicting_evidence_ids.append(ev.id)

        if twin:
            twin.add_hypothesis(h)
        created.append(h.model_dump())
        events.append({
            "type": "hypothesis_created",
            "hypothesis_id": h.id,
            "title": h.title,
            "price": h.price,
            "channel": h.channel,
            "segment": h.segment,
            "confidence": h.confidence,
            "assumptions": h.assumptions,
            "risks": h.risks,
            "message": f"Hypothesis: {h.title} @ ₹{h.price} via {h.channel}",
        })

    events.append({
        "type": "agent_complete",
        "agent": "Strategy Agent",
        "message": f"Generated {len(created)} competing hypotheses. {rationale}",
        "hypothesis_count": len(created),
        "superseded_ids": superseded_ids,
    })

    return {
        "twin": twin.model_dump() if twin else twin_data,
        "llm_calls": state.get("llm_calls", 0) + 1,
        "events": events,
    }
