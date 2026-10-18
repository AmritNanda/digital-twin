"""
Final Decision Agent — Node 7 in the LangGraph.

Responsibilities:
- Synthesize all evidence, simulations, and challenges into a final decision
- Produce a rich DecisionPackage:
    - Recommendation (action)
    - Why (rationale)
    - Supporting evidence (with IDs)
    - Counter-evidence
    - Simulation results for all hypotheses
    - Risks and bias warnings
    - Assumptions made
    - Confidence and uncertainty
    - What would change the recommendation
    - Recommended experiment
    - Evolution narrative (how the recommendation changed)
- Record a DecisionVersion in the twin
"""
from __future__ import annotations
import logging
from twin import DigitalTwin, DecisionVersion, to_confidence, to_str_list
from providers.llm import get_llm_provider, LLMUnavailableError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Final Decision Agent in a strategic intelligence system.

Your job is to synthesize everything discovered — company information, market evidence,
simulation results, adversarial challenges, and bias warnings — into a final
evidence-backed decision package.

Requirements:
1. Be honest about what is known vs assumed
2. Show the actual simulation results (not invented numbers)
3. Acknowledge remaining uncertainty
4. Clearly state what evidence supports and contradicts the recommendation
5. Specify what would change the recommendation
6. Propose a concrete real-world experiment to reduce uncertainty
7. Include the evolution narrative if the recommendation changed during analysis

Do NOT:
- Overstate confidence
- Ignore contradictions
- Present assumptions as facts
- Recommend without stating uncertainty bounds
"""

DECISION_PROMPT = """Complete Digital Twin State:
{twin_context}

Simulation Results:
{simulation_results}

Adversarial Challenges:
{challenges}

Bias Warnings:
{bias_warnings}

Evidence summary:
{evidence_summary}

Strategic Question: {question}

Produce the final decision package as JSON:
{{
  "recommendation": "specific action recommended",
  "rationale": "why this is the best option given evidence",
  "confidence": 0.72,
  "uncertainty_statement": "what drives remaining uncertainty",
  "selected_hypothesis_title": "...",
  "supporting_evidence": [
    "specific evidence excerpt that supports recommendation"
  ],
  "counter_evidence": [
    "specific evidence excerpt that challenges recommendation"
  ],
  "key_assumptions": [
    "assumption that underpins this recommendation"
  ],
  "risks": [
    "risk that could invalidate this recommendation"
  ],
  "bias_disclosures": [
    "any known bias in the evidence"
  ],
  "what_would_change_decision": [
    "if X were true, recommendation would change to Y"
  ],
  "recommended_experiment": "specific real-world test to run before full commitment",
  "evolution_narrative": "describe how the analysis evolved (initial direction → challenge → revision)",
  "open_questions": ["things still unknown"]
}}
"""


async def decision_node(state: dict) -> dict:
    """LangGraph node: synthesize final evidence-backed decision."""
    twin_data = state.get("twin", {})
    twin = DigitalTwin(**twin_data) if twin_data else None
    question = state["question"]
    llm = get_llm_provider()

    events = [{
        "type": "agent_start",
        "agent": "Decision Agent",
        "message": "Synthesizing final evidence-backed decision...",
        "iteration": state.get("iteration", 0),
    }]

    if not twin:
        final = {
            "recommendation": "Insufficient data to make a recommendation",
            "confidence": 0.1,
            "error": "Digital twin not populated",
        }
        return {"final_decision": final, "is_done": True, "events": events}

    # Latest simulation per current (non-superseded) hypothesis
    current_ids = {h.id for h in twin.current_hypotheses()}
    latest_sims = {}
    for s in twin.simulations:
        if s.hypothesis_id in current_ids:
            latest_sims[s.hypothesis_id] = s
    sims = list(latest_sims.values())
    titles = {h.id: h.title for h in twin.hypotheses}

    # Format simulation results
    sim_text = "\n".join(
        f"- {titles.get(s.hypothesis_id, s.hypothesis_id)}: price=₹{s.price}, channel={s.channel}, "
        f"avg_profit=₹{s.avg_profit:,.0f}, P(profit>0)={s.prob_positive*100:.1f}%, p50=₹{s.p50_profit:,.0f}"
        for s in sims
    ) or "(none)"

    # Format challenges
    challenge_text = "\n".join(
        f"- [{c.severity}] {c.weakness} (targets: {c.assumption_targeted})"
        for c in twin.challenges
    ) or "(none)"

    # Format evidence summary
    ev_summary = "\n".join(
        f"- [{ev.id}] {ev.source_type}: {ev.excerpt[:120]}"
        for ev in twin.evidence[-8:]
    ) or "(none)"

    try:
        result = await llm.complete_json(
            system=SYSTEM_PROMPT,
            user=DECISION_PROMPT.format(
                twin_context=twin.to_context_str(),
                simulation_results=sim_text,
                challenges=challenge_text,
                bias_warnings="\n".join(f"- {b}" for b in twin.bias_warnings) or "(none)",
                evidence_summary=ev_summary,
                question=question,
            ),
        )
    except LLMUnavailableError:
        raise
    except Exception as e:
        logger.error(f"Decision agent LLM error: {e}")
        result = {}

    confidence = to_confidence(result.get("confidence"))

    # Create DecisionVersion and add to twin
    version_num = len(twin.decisions) + 1
    selected_title = str(result.get("selected_hypothesis_title") or "").lower()
    leading = next(
        (h for h in twin.current_hypotheses() if selected_title and h.title.lower() == selected_title),
        twin.leading_hypothesis(),
    )
    dv = DecisionVersion(
        version=version_num,
        recommendation=str(result.get("recommendation") or "No recommendation"),
        rationale=str(result.get("rationale") or ""),
        selected_hypothesis_id=leading.id if leading else None,
        confidence=confidence,
        key_assumptions=to_str_list(result.get("key_assumptions")),
        open_questions=to_str_list(result.get("open_questions")),
        suggested_experiment=result.get("recommended_experiment"),
    )
    twin.decisions.append(dv)

    # Assemble the full DecisionPackage
    final = {
        "version": version_num,
        "recommendation": result.get("recommendation", ""),
        "rationale": result.get("rationale", ""),
        "confidence": confidence,
        "uncertainty_statement": result.get("uncertainty_statement", ""),
        "selected_hypothesis": leading.title if leading else None,
        "supporting_evidence": to_str_list(result.get("supporting_evidence")),
        "counter_evidence": to_str_list(result.get("counter_evidence")),
        "key_assumptions": to_str_list(result.get("key_assumptions")),
        "risks": to_str_list(result.get("risks")),
        "bias_disclosures": to_str_list(result.get("bias_disclosures")),
        "what_would_change": to_str_list(result.get("what_would_change_decision")),
        "recommended_experiment": result.get("recommended_experiment", ""),
        "evolution_narrative": result.get("evolution_narrative", ""),
        "open_questions": to_str_list(result.get("open_questions")),
        # Include simulation data for UI charts
        "simulations": [s.model_dump() for s in sims],
        "hypotheses": [h.model_dump() for h in twin.hypotheses],
        "challenges": [c.model_dump() for c in twin.challenges],
        "evidence": [e.model_dump() for e in twin.evidence],
        "twin_summary": twin.entity_summary(),
        "bias_warnings": twin.bias_warnings,
        "total_iterations": state.get("iteration", 0),
        "research_calls": state.get("research_calls", 0),
        "llm_calls": state.get("llm_calls", 0) + 1,
    }

    events.append({
        "type": "agent_complete",
        "agent": "Decision Agent",
        "message": f"Recommendation: {result.get('recommendation', '')}",
        "confidence": confidence,
        "evolution": result.get("evolution_narrative", ""),
    })
    events.append({
        "type": "workflow_complete",
        "message": "Analysis complete. Final decision package ready.",
    })

    return {
        "twin": twin.model_dump(),
        "final_decision": final,
        "is_done": True,
        "llm_calls": state.get("llm_calls", 0) + 1,
        "events": events,
    }
