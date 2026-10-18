"""
Digital Twin — the living structured representation of the company and its environment.

This module defines:
  - Entity types (Company, Product, Segment, Competitor, Market, etc.)
  - Relationship types
  - Evidence / Hypothesis / Strategy / Risk / Simulation / Decision nodes
  - A DigitalTwin container that holds the current state and supports updates

The twin lives in memory during a case run and is persisted to SQLite.
"""
from __future__ import annotations
import json
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return str(uuid.uuid4())[:8]


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """
    Tolerant numeric parser for LLM output.
    Handles numbers, numeric strings, and strings like "₹699", "1,200 units", "-1.2", "72%".
    Returns `default` if nothing numeric can be extracted.
    """
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("\u2212", "-")  # unicode minus
        m = _NUM_RE.search(cleaned)
        if m:
            try:
                return float(m.group())
            except ValueError:
                return default
    return default


def to_confidence(value: Any, default: float = 0.5) -> float:
    """Parse a confidence value into [0, 1]. Accepts 0.72, "0.72", 72, "72%"."""
    v = to_float(value, default)
    if v is None:
        v = default
    if v > 1.0:
        v = v / 100.0
    return max(0.0, min(1.0, v))


def to_str_list(value: Any) -> list[str]:
    """Coerce an LLM field into a list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v is not None and str(v).strip()]
    return [str(value)]


# ── Epistemic status ─────────────────────────────────────────────────────────

class EpistemicStatus(str, Enum):
    KNOWN = "known"           # directly observed / company-reported
    INFERRED = "inferred"     # derived from evidence by a rule/model
    ASSUMED = "assumed"       # declared scenario input
    UNKNOWN = "unknown"       # no accepted value
    CONTRADICTED = "contradicted"  # incompatible claims exist

    @classmethod
    def parse(cls, value: Any, default: "EpistemicStatus" = None) -> "EpistemicStatus":
        """Safe constructor — never raises on unexpected LLM output."""
        try:
            return cls(str(value).strip().lower())
        except (ValueError, AttributeError):
            return default or cls.INFERRED


# ── Base entity ──────────────────────────────────────────────────────────────

class TwinEntity(BaseModel):
    id: str = Field(default_factory=_id)
    type: str
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    epistemic: dict[str, EpistemicStatus] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    def update(self, **kwargs):
        for k, v in kwargs.items():
            self.attributes[k] = v
        self.updated_at = _now()


# ── Concrete entity types ─────────────────────────────────────────────────────

class Company(TwinEntity):
    type: str = "Company"

class Product(TwinEntity):
    type: str = "Product"

class CustomerSegment(TwinEntity):
    type: str = "CustomerSegment"

class Competitor(TwinEntity):
    type: str = "Competitor"

class Market(TwinEntity):
    type: str = "Market"

class Constraint(TwinEntity):
    type: str = "Constraint"

class Objective(TwinEntity):
    type: str = "Objective"


# ── Evidence ─────────────────────────────────────────────────────────────────

class Evidence(BaseModel):
    id: str = Field(default_factory=_id)
    source: str          # URL, document name, or "internal"
    source_type: str     # "internal" | "web" | "news" | "fixture"
    excerpt: str
    relevance_score: float = 0.0
    tags: list[str] = Field(default_factory=list)
    epistemic: EpistemicStatus = EpistemicStatus.KNOWN
    created_at: str = Field(default_factory=_now)


# ── Hypothesis / Strategy ─────────────────────────────────────────────────────

class Hypothesis(BaseModel):
    id: str = Field(default_factory=_id)
    title: str
    description: str
    price: Optional[float] = None
    channel: Optional[str] = None
    segment: Optional[str] = None
    assumptions: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    expected_outcome: Optional[str] = None
    confidence: float = 0.5       # 0..1
    status: str = "active"        # active | weakened | rejected | selected | superseded
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


# ── Simulation result ─────────────────────────────────────────────────────────

class SimulationResult(BaseModel):
    id: str = Field(default_factory=_id)
    hypothesis_id: str
    price: float
    channel: str
    avg_profit: float
    prob_positive: float          # P(profit > 0)
    p10_profit: float
    p50_profit: float
    p90_profit: float
    avg_monthly_demand: float
    assumptions_used: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now)


# ── Challenge (Devil's Advocate finding) ─────────────────────────────────────

class Challenge(BaseModel):
    id: str = Field(default_factory=_id)
    hypothesis_id: str
    weakness: str
    assumption_targeted: str
    severity: str              # "critical" | "moderate" | "minor"
    evidence_gap: Optional[str] = None
    triggered_research: Optional[str] = None
    resolution: Optional[str] = None
    created_at: str = Field(default_factory=_now)


# ── Relationship ─────────────────────────────────────────────────────────────

class Relationship(BaseModel):
    id: str = Field(default_factory=_id)
    source_id: str
    target_id: str
    relation: str   # e.g. "COMPETES_WITH", "SERVES", "SUBJECT_TO", "SUPPORTS"
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now)


# ── Decision ─────────────────────────────────────────────────────────────────

class DecisionVersion(BaseModel):
    version: int
    recommendation: str
    rationale: str
    selected_hypothesis_id: Optional[str] = None
    confidence: float
    key_assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    suggested_experiment: Optional[str] = None
    timestamp: str = Field(default_factory=_now)


# ── The living Digital Twin ───────────────────────────────────────────────────

class DigitalTwin(BaseModel):
    """
    The living representation of the company and its environment.
    Mutated by agents as they discover new information.
    """
    case_id: str
    question: str

    # Entities
    companies: list[Company] = Field(default_factory=list)
    products: list[Product] = Field(default_factory=list)
    segments: list[CustomerSegment] = Field(default_factory=list)
    competitors: list[Competitor] = Field(default_factory=list)
    markets: list[Market] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    objectives: list[Objective] = Field(default_factory=list)

    # Intelligence
    evidence: list[Evidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    simulations: list[SimulationResult] = Field(default_factory=list)
    challenges: list[Challenge] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)

    # Decisions (grows with each revision)
    decisions: list[DecisionVersion] = Field(default_factory=list)

    # Tracking
    unknowns: list[str] = Field(default_factory=list)
    bias_warnings: list[str] = Field(default_factory=list)
    iteration: int = 0
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    def touch(self):
        self.updated_at = _now()

    def add_evidence(self, ev: Evidence) -> None:
        self.evidence.append(ev)
        self.touch()

    def add_hypothesis(self, h: Hypothesis) -> None:
        self.hypotheses.append(h)
        self.touch()

    def add_simulation(self, s: SimulationResult) -> None:
        self.simulations.append(s)
        self.touch()

    def add_challenge(self, c: Challenge) -> None:
        self.challenges.append(c)
        self.touch()

    def add_relationship(self, source_id: str, target_id: str, relation: str, **attrs) -> None:
        r = Relationship(source_id=source_id, target_id=target_id, relation=relation, attributes=attrs)
        self.relationships.append(r)
        self.touch()

    def get_entity_by_id(self, eid: str) -> Optional[TwinEntity]:
        all_entities = (
            self.companies + self.products + self.segments +
            self.competitors + self.markets + self.constraints + self.objectives
        )
        for e in all_entities:
            if e.id == eid:
                return e
        return None

    def get_evidence_by_id(self, eid: str) -> Optional[Evidence]:
        for ev in self.evidence:
            if ev.id == eid:
                return ev
        return None

    def get_hypothesis_by_id(self, hid: str) -> Optional[Hypothesis]:
        for h in self.hypotheses:
            if h.id == hid:
                return h
        return None

    def leading_hypothesis(self) -> Optional[Hypothesis]:
        active = [h for h in self.hypotheses if h.status in ("active", "weakened")]
        if not active:
            return None
        # Prefer non-weakened hypotheses; fall back to weakened ones
        return max(active, key=lambda h: (h.status == "active", h.confidence))

    def current_hypotheses(self) -> list[Hypothesis]:
        """Hypotheses still under consideration (not superseded/rejected)."""
        return [h for h in self.hypotheses if h.status not in ("superseded", "rejected")]

    def primary_product(self, create: bool = True) -> Optional[Product]:
        """Return the main product; optionally create a placeholder so parameters are never lost."""
        if self.products:
            return self.products[0]
        if not create:
            return None
        p = Product(name="Primary product", attributes={})
        self.products.append(p)
        self.touch()
        return p

    def entity_summary(self) -> dict:
        return {
            "companies": len(self.companies),
            "products": len(self.products),
            "segments": len(self.segments),
            "competitors": len(self.competitors),
            "markets": len(self.markets),
            "evidence": len(self.evidence),
            "hypotheses": len(self.hypotheses),
            "simulations": len(self.simulations),
            "challenges": len(self.challenges),
        }

    def to_context_str(self) -> str:
        """Compact representation for LLM context."""
        lines = [f"[DIGITAL TWIN — Case: {self.case_id}]",
                 f"Question: {self.question}", ""]
        if self.companies:
            c = self.companies[0]
            lines.append(f"Company: {c.name}")
            for k, v in c.attributes.items():
                lines.append(f"  {k}: {v}")
        if self.products:
            p = self.products[0]
            lines.append(f"Product: {p.name}")
            for k, v in p.attributes.items():
                lines.append(f"  {k}: {v}")
        if self.segments:
            lines.append("Customer Segments:")
            for s in self.segments:
                lines.append(f"  - {s.name}: {json.dumps(s.attributes)}")
        if self.competitors:
            lines.append("Competitors:")
            for co in self.competitors:
                lines.append(f"  - {co.name}: {json.dumps(co.attributes)}")
        if self.markets:
            lines.append("Markets:")
            for m in self.markets:
                lines.append(f"  - {m.name}: {json.dumps(m.attributes)}")
        if self.constraints:
            lines.append("Constraints:")
            for cn in self.constraints:
                lines.append(f"  - {cn.name}: {cn.attributes.get('value', '')}")
        if self.unknowns:
            lines.append("Known Unknowns:")
            for u in self.unknowns:
                lines.append(f"  ? {u}")
        if self.evidence:
            lines.append(f"\nEvidence ({len(self.evidence)} items):")
            for ev in self.evidence[-6:]:   # last 6
                lines.append(f"  [{ev.id}] ({ev.source_type}) {ev.excerpt[:120]}")
        return "\n".join(lines)
