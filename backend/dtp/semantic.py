"""Mandatory semantic validators (SRS Annex C) that need no repository access.

Repository-dependent checks (reference closure, snapshot membership, lineage
currentness) live with the canonical store in a later stage. Every function returns
a list of violation strings; empty means this check passed. Passing here never
implies evidential validity.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any


def _fin(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def check_distribution(d: dict) -> list[str]:
    v: list[str] = []
    fam = d.get("family")
    nums = {k: x for k, x in d.items() if k != "family" and not isinstance(x, (dict, list, str))}
    for k, x in nums.items():
        if not _fin(x):
            v.append(f"{k} not finite")
    if v:
        return v
    if fam == "UNIFORM" and not d["low"] < d["high"]:
        v.append("UNIFORM requires low < high")
    elif fam == "TRIANGULAR":
        if not d["low"] < d["high"]:
            v.append("TRIANGULAR requires low < high")
        if not d["low"] <= d["mode"] <= d["high"]:
            v.append("TRIANGULAR requires low <= mode <= high")
    elif fam == "BETA" and not (d["alpha"] > 0 and d["beta"] > 0):
        v.append("BETA shape parameters must be positive")
    elif fam in ("NORMAL",) and not d["stddev"] > 0:
        v.append("NORMAL stddev must be positive")
    elif fam == "LOGNORMAL" and not d["log_stddev"] > 0:
        v.append("LOGNORMAL log_stddev must be positive")
    return v


def check_time_scope(scope: dict, *, recorded_at: str | None = None,
                     knowledge_cutoff: str | None = None) -> list[str]:
    """[valid_from, valid_to) half-open; null = unknown/unbounded, never 'now'."""
    v: list[str] = []
    vf, vt = scope.get("valid_from"), scope.get("valid_to")
    if vf is not None and vt is not None and not _ts(vf) < _ts(vt):
        v.append("valid_from must be before valid_to")
    if recorded_at and knowledge_cutoff and _ts(recorded_at) > _ts(knowledge_cutoff):
        v.append("record first recorded after knowledge cutoff (future knowledge)")
    return v


def valid_at(scope: dict, instant: str) -> bool:
    """Half-open containment; unknown endpoints are treated as unbounded."""
    t = _ts(instant)
    vf, vt = scope.get("valid_from"), scope.get("valid_to")
    return (vf is None or _ts(vf) <= t) and (vt is None or t < _ts(vt))


def as_known(records: list[dict], cutoff: str, valid_instant: str | None = None) -> list[dict]:
    """AT-007: latest revision of each claim recorded <= cutoff (optionally valid at an instant)."""
    latest: dict[str, dict] = {}
    for r in sorted(records, key=lambda r: (_ts(r["recorded_at"]), r["revision"])):
        if _ts(r["recorded_at"]) <= _ts(cutoff):
            latest[r["id"]] = r
    out = [r for r in latest.values() if r.get("status") != "WITHDRAWN"]
    if valid_instant:
        out = [r for r in out if valid_at(r["scope"], valid_instant)]
    return out


def check_claim(c: dict, *, authorized_assumptions: frozenset[str] = frozenset()) -> list[str]:
    v: list[str] = []
    st = c["epistemic_state"]
    val = c.get("value")
    if st == "UNKNOWN" and val is not None:
        v.append("UNKNOWN must not carry a selected value")
    if st == "CONTRADICTED" and len(c.get("competing_claim_refs", [])) < 1:
        v.append("CONTRADICTED must retain competing claim refs")
    if st == "KNOWN" and not c.get("evidence_refs"):
        v.append("KNOWN requires direct evidence refs")
    if st == "INFERRED" and not c.get("derivation_refs"):
        v.append("INFERRED requires derivation refs")
    if st == "ASSUMED":
        refs = c.get("assumption_refs", [])
        if not refs:
            v.append("ASSUMED requires assumption refs")
        elif authorized_assumptions and any(r["id"] not in authorized_assumptions for r in refs):
            v.append("ASSUMED uses unauthorized assumption")
    if val is not None and isinstance(val, dict):
        if val.get("currency") is None and val.get("type") in ("DECIMAL", "NUMBER") and \
                str(val.get("unit", "")).upper() in ("INR", "USD", "EUR", "GBP"):
            v.append("monetary value requires explicit currency")
    v += check_time_scope(c["scope"])
    return v


def check_origin(parent_origins: list[str], derived_origin: str) -> list[str]:
    """FIXTURE never becomes REAL by derivation."""
    if derived_origin == "REAL" and "FIXTURE" in parent_origins:
        return ["derived REAL artifact depends on FIXTURE input"]
    return []


def check_metric(m: dict) -> list[str]:
    a = m["availability"]
    val = m.get("value")
    if a == "AVAILABLE":
        return [] if _fin(val) else ["AVAILABLE metric requires finite numeric value"]
    v = []
    if val is not None:
        v.append(f"{a} metric must have null value")
    if not m.get("reason"):
        v.append(f"{a} metric requires reason")
    return v


def check_simulation(r: dict) -> list[str]:
    v: list[str] = []
    if r["invalid_draw_count"] > r["draw_count"]:
        v.append("invalid_draw_count exceeds draw_count")
    if r["draw_count"] <= 0:
        v.append("draw_count must be positive")
    sset = {s["id"] for s in r["strategy_refs"]}
    mset = {m.get("strategy_ref", {}).get("id") for m in r["metrics_by_strategy"] if isinstance(m, dict)}
    if mset and mset != sset:
        v.append("strategy set and metric set misalign")
    for entry in r["metrics_by_strategy"]:
        for m in (entry.get("metrics", []) if isinstance(entry, dict) else []):
            v += check_metric(m)
    return v


def check_scenario(p: dict, *, allowed_keys: frozenset[str],
                   identified_models: frozenset[str] = frozenset()) -> list[str]:
    v: list[str] = []
    for patch in p["patches"]:
        k = patch.get("parameter_key") or patch.get("key")
        if k is not None and k not in allowed_keys:
            v.append(f"patch key {k!r} not allowed by model")
    if p["semantic_type"] == "CAUSAL_COUNTERFACTUAL":
        rev = p.get("identification_review_ref")
        if not rev or p["model_ref"]["id"] not in identified_models:
            v.append("causal counterfactual requires an accepted identification review for the model; "
                     "label as SENSITIVITY otherwise")
    return v


def check_decision(d: dict, *, feasible_strategy_ids: frozenset[str],
                   verification_failed: bool, definitive_gates_passed: bool) -> list[str]:
    v: list[str] = []
    out, sel = d["outcome"], d.get("selected_strategy_ref")
    if out in ("RECOMMEND", "CONDITIONAL"):
        if not sel:
            v.append(f"{out} requires a selected strategy")
        elif sel["id"] not in feasible_strategy_ids:
            v.append("selected strategy is not feasible")
    if out == "RECOMMEND" and (verification_failed or not definitive_gates_passed):
        v.append("definitive RECOMMEND blocked: verification/gates not passed")
    if d["stop_reason"] == "CONVERGED" and (verification_failed or d.get("unresolved_issues")) \
            and out == "RECOMMEND":
        v.append("CONVERGED cannot coexist with failed verification or unresolved material issues")
    return v


def check_challenge(c: dict, *, authorized_disposition: bool) -> list[str]:
    if c["status"] == "RESOLVED":
        v = []
        if not c.get("resolution_refs"):
            v.append("RESOLVED requires resolution refs")
        if not authorized_disposition:
            v.append("RESOLVED requires authorized disposition")
        return v
    return []


def check_event(e: dict) -> list[str]:
    v = []
    if e["id"] != e["event_id"]:
        v.append("id must equal event_id")
    if e["aggregate_revision"] < 1:
        v.append("aggregate_revision must be positive")
    return v


def check_verification(r: dict, *, definitive: bool) -> list[str]:
    v = []
    for c in r["checks"]:
        if c.get("result") == "FAIL" and c.get("mandatory", True) and definitive:
            v.append(f"mandatory check failed: {c.get('check_id') or c.get('name')}")
        if c.get("result") == "NOT_APPLICABLE" and not c.get("reason"):
            v.append("NOT_APPLICABLE requires justified reason")
    return v


def check_no_cycles(edges: list[tuple[str, str]]) -> list[str]:
    """Dependency/lineage graph must be acyclic (Kahn)."""
    nodes: dict[str, int] = {}
    adj: dict[str, list[str]] = {}
    for a, b in edges:
        nodes.setdefault(a, 0)
        nodes.setdefault(b, 0)
        adj.setdefault(a, []).append(b)
        nodes[b] += 1
    q = [n for n, d in nodes.items() if d == 0]
    seen = 0
    while q:
        n = q.pop()
        seen += 1
        for m in adj.get(n, []):
            nodes[m] -= 1
            if nodes[m] == 0:
                q.append(m)
    return [] if seen == len(nodes) else ["dependency cycle detected"]
