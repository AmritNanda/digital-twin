"""
LangGraph shared state definition.

The CaseRunState is the single source of truth passed between all graph nodes.
Agents read from it and return state updates — they never share mutable objects.
"""
from __future__ import annotations
from typing import Annotated, Any, Optional
import operator
from langgraph.graph import MessagesState
from twin import DigitalTwin


class CaseRunState(MessagesState):
    # Identity
    case_id: str
    question: str
    doc_id: Optional[str]

    # The living twin (serialised as dict for LangGraph compatibility)
    twin: Optional[dict]        # DigitalTwin.model_dump()

    # Agent loop controls
    iteration: int
    research_calls: int
    llm_calls: int
    max_iterations: int
    max_research_calls: int

    # Planning
    unknowns: list[str]         # Identified gaps to investigate
    research_tasks: list[dict]  # Queued research requests [{query, priority, reason}]
    completed_tasks: list[str]  # Completed task descriptions

    # Evidence accumulated
    evidence_summaries: list[str]

    # Agent outputs (accumulated with operator.add)
    events: Annotated[list[dict], operator.add]  # Streaming events for the UI

    # Control flow flags
    needs_more_research: bool
    adversarial_triggered_replan: bool
    is_done: bool
    stop_reason: Optional[str]

    # Final result
    final_decision: Optional[dict]
