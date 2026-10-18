"""
Devil's Advocate Agent — Node 6 in the LangGraph.

Responsibilities:
- Attempt to DISPROVE the leading hypothesis
- Identify which assumptions are weakest
- Check for: source concentration, demographic bias, confirmation bias,
  unrealistic assumptions, competitor response, regulatory risk,
  financial fragility, insufficient evidence
- If a weakness is CRITICAL → trigger a new research cycle
- Update hypothesis confidence accordingly
- Create Challenge records in the twin

This is NOT performative disagreement.
The agent genuinely tries to find a reason the recommendation is wrong.
"""
from __future__ import annotations
import logging
from twin import DigitalTwin, Challenge, to_float
from providers.llm import get_llm_provider, LLMUnavailableError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Devil's Advocate agent in a strategic decision intelligence system.

Your ONLY job is to attempt to disprove the current leading recommendation.

You must be genuinely adversarial — not performatively critical.

Examine the leading hypothesis and ask:
1. What assumptions does it critically depend on?
2. Which assumptions have weak or no evidence?
3. Is the evidence biased? (only online users? only positive reviews? single geography?)
4. Are sources concentrated? (many articles from the same press release?)
5. Could a competitor respond in a way that invalidates this strategy?
6. Are there regulatory or compliance risks not accounted for?
7. Does the financial model depend on CAC or demand numbers that are speculative?
8. Is there a scenario where this hypothesis performs catastrophically?
9. Does the evidence cover the right population (target segment)?
10. What would make this recommendation WRONG?

For each weakness found, assign a severity:
- "critical": would change the recommendation if true
- "moderate": reduces confidence significantly
- "minor": worth noting but unlikely to change the outcome

If you find a CRITICAL weakness that requires more evidence,
specify the exact research query needed to resolve it.
"""

DEVIL_PROMPT = """Leading Hypothesis to challenge:
Title: {title}
Price: ₹{price}
Channel: {channel}
Segment: {segment}
Assumptions: {assumptions}
Risks already identified: {risks}
Confidence from simulation: {confidence}

Evidence used:
{evidence}

Bias warnings so far:
{bias_warnings}

Known unknowns:
{unknowns}

Digital Twin Summary:
{twin_context}

ATTEMPT TO DISPROVE this recommendation. Produce JSON:
{{
  "challenges": [
    {{
      "weakness": "clear description of the weakness",
      "assumption_targeted": "which assumption this attacks",
      "severity": "critical|moderate|minor",
      "evidence_gap": "what additional evidence would resolve this, or null if resolvable from logic",
      "research_query": "specific search query to gather missing evidence, or null if no research needed"
    }}
  ],
  "verdict": "strong|weak|uncertain",
  "verdict_rationale": "concise explanation of whether the hypothesis survived challenge",
  "confidence_adjustment": -0.15,
  "triggers_replan": true
}}

Be honest. If the hypothesis is actually well-supported, say so.
"""


async def devil_node(state: dict) -> dict:
    """LangGraph node: adversarial challenge of the leading hypothesis."""
    twin_data = state.get("twin", {})
    twin = DigitalTwin(**twin_data) if twin_data else None

    if not twin or not twin.hypotheses:
        return {"events": [{
            "type": "agent_skip",
            "agent": "Devil's Advocate",
            "message": "No hypothesis to challenge",
        }]}

    leading = twin.leading_hypothesis()
    if not leading:
        return {"events": [{
            "type": "agent_skip",
            "agent": "Devil's Advocate",
            "message": "No active hypothesis to challenge",
        }]}

    question = state["question"]
    llm = get_llm_provider()

    events = [{
        "type": "agent_start",
        "agent": "Devil's Advocate",
        "message": f"Attempting to disprove '{leading.title}'...",
        "hypothesis": leading.title,
        "iteration": state.get("iteration", 0),
    }]

    # Gather evidence for context
    all_evidence = "\n".join(
        f"- [{ev.id}] {ev.excerpt[:120]} ({ev.source_type})"
        for ev in twin.evidence[-10:]
    )

    try:
        result = await llm.complete_json(
            system=SYSTEM_PROMPT,
            user=DEVIL_PROMPT.format(
                title=leading.title,
                price=leading.price or "?",
                channel=leading.channel or "?",
                segment=leading.segment or "?",
                assumptions="\n".join(f"- {a}" for a in leading.assumptions),
                risks="\n".join(f"- {r}" for r in leading.risks),
                confidence=leading.confidence,
                evidence=all_evidence or "(none)",
                bias_warnings="\n".join(f"- {b}" for b in twin.bias_warnings) or "(none)",
                unknowns="\n".join(f"- {u}" for u in twin.unknowns) or "(none)",
                twin_context=twin.to_context_str(),
            ),
        )
    except LLMUnavailableError:
        raise
    except Exception as e:
        logger.error(f"Devil's advocate LLM error: {e}")
        result = {}

    challenges_data = [c for c in (result.get("challenges") or []) if isinstance(c, dict)]
    verdict = str(result.get("verdict") or "uncertain").lower()
    rationale = result.get("verdict_rationale", "")
    confidence_adj = max(-0.5, min(0.5, to_float(result.get("confidence_adjustment"), 0.0)))
    triggers_replan = bool(result.get("triggers_replan", False))

    # Create Challenge objects and update twin
    new_research_tasks = []
    for cd in challenges_data:
        severity = str(cd.get("severity") or "minor").lower()
        ch = Challenge(
            hypothesis_id=leading.id,
            weakness=cd.get("weakness", ""),
            assumption_targeted=cd.get("assumption_targeted", ""),
            severity=severity,
            evidence_gap=cd.get("evidence_gap"),
            triggered_research=cd.get("research_query"),
        )
        twin.add_challenge(ch)

        events.append({
            "type": "challenge_raised",
            "agent": "Devil's Advocate",
            "challenge_id": ch.id,
            "weakness": ch.weakness,
            "assumption": ch.assumption_targeted,
            "severity": severity,
            "message": f"[{severity.upper()}] {ch.weakness}",
        })

        # If critical, queue research to resolve
        if severity == "critical" and cd.get("research_query"):
            new_research_tasks.append({
                "query": cd["research_query"],
                "topic": "adversarial_evidence",
                "reason": f"Devil's Advocate challenge: {ch.weakness}",
                "priority": 1,
            })

    # Adjust hypothesis confidence
    leading.confidence = max(0.05, min(0.99, leading.confidence + confidence_adj))
    leading.updated_at = next(iter([c.created_at for c in twin.challenges[-1:]]), leading.updated_at)

    if verdict == "weak":
        leading.status = "weakened"

    # Bias audit (only add each warning once across repeated passes)
    source_types = [ev.source_type for ev in twin.evidence]
    audit = []
    if source_types and source_types.count("web") > len(source_types) * 0.8:
        audit.append("Source concentration: >80% of evidence from web searches")
    if "fixture" in source_types:
        audit.append("Demo mode: some evidence from pre-built fixtures (disclosed)")
    twin.bias_warnings.extend(w for w in audit if w not in twin.bias_warnings)

    events.append({
        "type": "agent_complete",
        "agent": "Devil's Advocate",
        "verdict": verdict,
        "hypothesis_id": leading.id,
        "hypothesis_status": leading.status,
        "hypothesis_confidence": leading.confidence,
        "rationale": rationale,
        "challenge_count": len(challenges_data),
        "critical_challenges": sum(1 for c in challenges_data if c.get("severity") == "critical"),
        "triggers_replan": triggers_replan or bool(new_research_tasks),
        "confidence_adjustment": confidence_adj,
        "message": f"Verdict: {verdict}. {rationale}",
        "bias_warnings": twin.bias_warnings[-3:],
    })

    return {
        "twin": twin.model_dump(),
        "adversarial_triggered_replan": triggers_replan or bool(new_research_tasks),
        "research_tasks": state.get("research_tasks", []) + new_research_tasks,
        "llm_calls": state.get("llm_calls", 0) + 1,
        "events": events,
    }
