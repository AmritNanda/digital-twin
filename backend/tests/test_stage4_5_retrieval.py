"""Stage 4 & 5 integration tests: Claim-evidence closure, vector embeddings, lexical search,
reciprocal rank fusion (RRF), and hybrid retrieval (AT-009, AT-010, AT-012).
"""
from __future__ import annotations

import time
import pytest

from dtp import repo
from dtp.contracts import load_fixture_examples
from dtp.db import tenant_tx
from dtp.identity import Op, Principal, Role
from dtp.intake.service import ingest_file, link_claim_evidence
from dtp.retrieval import compute_rrf, embed_query, embed_texts, hybrid_search


@pytest.fixture()
def retrieval_world(postgres_ready):
    tid, owner_id = repo.bootstrap_tenant("retrieval_t", f"o{time.time_ns()}@retrieval.test")
    owner = Principal(tid, owner_id, frozenset({Role.OWNER}), grants=frozenset({(Op.ACCEPT, "financial")}))
    case = repo.create_case(owner, title="Retrieval Case", objective="Market test", horizon_days=90, origin="FIXTURE")

    # Ingest document with exact financial facts
    doc_content = (
        b"# Nila Home Unit Economics\n"
        b"Our starter kit unit selling price is $49.00 net of tax.\n"
        b"Cost of goods sold (COGS) is strictly $18.50 per unit.\n"
        b"Fulfillment and packaging cost is $4.20 per package.\n"
        b"Paid social customer acquisition cost (CAC) averaged $14.00 across testing.\n"
        b"Fixed monthly operating overhead stands at $12,000.\n"
    )
    doc_res = ingest_file(owner, case, "economics.txt", doc_content, origin="FIXTURE")

    return {"tid": tid, "owner": owner, "case": case, "doc_res": doc_res}


def test_vector_embeddings_dimensions():
    embs = embed_texts(["Strategic pricing test", "Customer demand elasticity"])
    assert len(embs) == 2
    assert len(embs[0]) == 384
    assert len(embs[1]) == 384

    q_emb = embed_query("What is unit COGS?")
    assert len(q_emb) == 384


def test_reciprocal_rank_fusion_math():
    lexical = ["span_1", "span_2", "span_3"]
    vector = ["span_2", "span_4", "span_1"]
    graph = ["span_2"]

    scores = compute_rrf(lexical, vector, graph, k=60)

    # span_2 appears in all 3 lists -> should rank highest
    top_id = next(iter(scores.keys()))
    assert top_id == "span_2"
    assert scores["span_2"] > scores["span_1"]


def test_hybrid_search_end_to_end(retrieval_world):
    owner = retrieval_world["owner"]
    case_id = retrieval_world["case"]

    pack = hybrid_search(owner, case_id, "What is the unit cost and COGS?", limit=5)

    assert pack.query == "What is the unit cost and COGS?"
    assert len(pack.selected_spans) > 0

    # Ensure top spans cite COGS
    cogs_found = any("COGS" in s.text or "cost" in s.text.lower() for s in pack.selected_spans)
    assert cogs_found

    # Ensure locators & source tracking are intact
    for s in pack.selected_spans:
        assert s.locator["type"] == "TEXT_LINES"
        assert len(s.sources) > 0


def test_claim_evidence_closure(retrieval_world):
    owner = retrieval_world["owner"]
    case_id = retrieval_world["case"]
    tid = retrieval_world["tid"]

    # 1. Propose claim
    ex = next(e for e in load_fixture_examples() if e["artifact_type"] == "ClaimProposal")
    ex["tenant_id"] = tid
    ex["origin"] = "FIXTURE"
    ex["proposition"] = "Unit COGS is $18.50"
    claim_id, rev = repo.propose_claim(owner, case_id, ex)

    # 2. Get span id from ingested doc
    with tenant_tx(tid) as c:
        span = c.execute("SELECT id FROM evidence_spans WHERE text LIKE '%COGS%'").fetchone()
        assert span is not None
        span_id = str(span["id"])

    # 3. Link claim to exact evidence span
    link_claim_evidence(owner, claim_id, rev, span_id, quote="Cost of goods sold (COGS) is strictly $18.50 per unit.")

    # 4. Verify link in DB
    with tenant_tx(tid) as c:
        link = c.execute(
            "SELECT * FROM claim_evidence WHERE claim_id=%s AND revision=%s AND evidence_span_id=%s",
            (claim_id, rev, span_id),
        ).fetchone()
        assert link is not None
        assert link["support_type"] == "DIRECT"
        assert "COGS" in link["quote"]
