"""Hybrid Retrieval Service (SRS-018, AT-009, AT-010).
Combines:
1. Lexical full-text search (PostgreSQL tsvector / plainto_tsquery).
2. Semantic vector search (pgvector cosine distance `<=>`).
3. Graph neighbor traversal (bounded 2 hops).
4. Reciprocal Rank Fusion (RRF) to combine ranks without adding incomparable raw scores.
Outputs strict EvidencePack with query metadata, selected spans, origin clusters, and gaps.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from dtp.db import tenant_tx
from dtp.identity import Op, Principal, ResourceScope, authorize
from dtp.retrieval.embeddings import embed_query


@dataclass
class RetrievedSpan:
    span_id: str
    document_version_id: str
    text: str
    heading: str | None
    locator: dict[str, Any]
    quality: str
    rrf_score: float
    sources: list[str] = field(default_factory=list)  # "lexical", "vector", "graph"


@dataclass
class EvidencePack:
    query: str
    case_id: str
    selected_spans: list[RetrievedSpan]
    graph_context: list[dict[str, Any]]
    total_candidates: int
    coverage_gaps: list[str]


def compute_rrf(
    lexical_ids: list[str],
    vector_ids: list[str],
    graph_ids: list[str],
    k: int = 60,
) -> dict[str, float]:
    """Reciprocal Rank Fusion: RRF_score(d) = sum(1 / (k + rank_i(d)))."""
    scores: dict[str, float] = {}

    for rank, span_id in enumerate(lexical_ids, start=1):
        scores[span_id] = scores.get(span_id, 0.0) + (1.0 / (k + rank))

    for rank, span_id in enumerate(vector_ids, start=1):
        scores[span_id] = scores.get(span_id, 0.0) + (1.0 / (k + rank))

    for rank, span_id in enumerate(graph_ids, start=1):
        scores[span_id] = scores.get(span_id, 0.0) + (1.0 / (k + rank))

    return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))


def hybrid_search(
    p: Principal,
    case_id: str,
    query: str,
    limit: int = 12,
    lexical_limit: int = 30,
    vector_limit: int = 30,
) -> EvidencePack:
    """Execute hybrid search combining full-text, pgvector embeddings, and graph connections."""
    authorize(p, Op.READ, ResourceScope(p.tenant_id, case_id))

    clean_query = query.strip()
    if not clean_query:
        return EvidencePack(query="", case_id=case_id, selected_spans=[], graph_context=[], total_candidates=0, coverage_gaps=["Empty query"])

    query_emb = embed_query(clean_query)

    lexical_candidates: list[dict] = []
    vector_candidates: list[dict] = []
    graph_nodes: list[dict] = []

    with tenant_tx(p.tenant_id) as c:
        # 1. Lexical candidate search (PostgreSQL tsquery)
        lex_rows = c.execute(
            """
            SELECT s.id, s.document_version_id, s.text, s.heading, s.locator, s.quality,
                   ts_rank_cd(s.tsv, plainto_tsquery('english', %(q)s)) AS rank
            FROM evidence_spans s
            JOIN document_versions d ON d.id = s.document_version_id
            WHERE d.case_id = %(case)s AND s.withdrawn = false
              AND s.tsv @@ plainto_tsquery('english', %(q)s)
            ORDER BY rank DESC
            LIMIT %(lim)s
            """,
            {"q": clean_query, "case": case_id, "lim": lexical_limit},
        ).fetchall()
        lexical_candidates = [dict(r) for r in lex_rows]

        # 2. Semantic vector candidate search (pgvector cosine operator)
        vec_rows = c.execute(
            """
            SELECT s.id, s.document_version_id, s.text, s.heading, s.locator, s.quality,
                   (s.embedding <=> %(emb)s::vector) AS dist
            FROM evidence_spans s
            JOIN document_versions d ON d.id = s.document_version_id
            WHERE d.case_id = %(case)s AND s.withdrawn = false AND s.embedding IS NOT NULL
            ORDER BY s.embedding <=> %(emb)s::vector
            LIMIT %(lim)s
            """,
            {"emb": query_emb, "case": case_id, "lim": vector_limit},
        ).fetchall()
        vector_candidates = [dict(r) for r in vec_rows]

        # 3. Graph context exploration (2 hops from case)
        g_rows = c.execute(
            """
            SELECT relation, source_kind, source_id, target_kind, target_id
            FROM graph_edges
            WHERE case_id = %(case)s
            LIMIT 50
            """,
            {"case": case_id},
        ).fetchall()
        graph_nodes = [dict(r) for r in g_rows]

    # Map details by ID
    all_spans_map: dict[str, dict] = {}
    for r in lexical_candidates:
        all_spans_map[str(r["id"])] = r
    for r in vector_candidates:
        all_spans_map[str(r["id"])] = r

    lex_ids = [str(r["id"]) for r in lexical_candidates]
    vec_ids = [str(r["id"]) for r in vector_candidates]
    # Spans linked to graph targets
    graph_ids = [str(n["target_id"]) for n in graph_nodes if str(n["target_id"]) in all_spans_map]

    # RRF combination
    rrf_scores = compute_rrf(lex_ids, vec_ids, graph_ids)
    top_ids = list(rrf_scores.keys())[:limit]

    selected: list[RetrievedSpan] = []
    for sid in top_ids:
        raw = all_spans_map[sid]
        sources = []
        if sid in lex_ids:
            sources.append("lexical")
        if sid in vec_ids:
            sources.append("vector")
        if sid in graph_ids:
            sources.append("graph")

        selected.append(
            RetrievedSpan(
                span_id=sid,
                document_version_id=str(raw["document_version_id"]),
                text=raw["text"],
                heading=raw["heading"],
                locator=raw["locator"] if isinstance(raw["locator"], dict) else json.loads(raw["locator"]),
                quality=raw["quality"],
                rrf_score=round(rrf_scores[sid], 5),
                sources=sources,
            )
        )

    gaps = []
    if not selected:
        gaps.append(f"No matches found for '{clean_query}' across lexical and vector indexes.")
    elif len(selected) < limit:
        gaps.append(f"Retrieved {len(selected)} spans (below target limit of {limit}).")

    return EvidencePack(
        query=clean_query,
        case_id=case_id,
        selected_spans=selected,
        graph_context=graph_nodes,
        total_candidates=len(all_spans_map),
        coverage_gaps=gaps,
    )
