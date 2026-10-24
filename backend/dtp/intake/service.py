"""Intake service: coordinate security validation, object storage, database registration,
exact-anchor parsing, and evidence span storage into PostgreSQL (SRS-005, SRS-006, AT-001, AT-002, AT-041).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from dtp.db import tenant_tx
from dtp.identity import AuthorizationError, NotFound, Op, Principal, ResourceScope, authorize
from dtp.intake.parsers import ParseResult, parse_bytes
from dtp.intake.security import Rejected, detect
from dtp.intake.storage import object_store
from dtp.repo import emit_event
from dtp.retrieval.embeddings import embed_texts


class IntakeError(Exception):
    pass


def ingest_file(
    p: Principal,
    case_id: str,
    declared_name: str,
    data: bytes,
    declared_type: str | None = None,
    data_class: str = "INTERNAL",
    origin: str = "REAL",
) -> dict[str, Any]:
    """Ingest a file for a case with strict security, hashing, storage, and span extraction."""
    authorize(p, Op.PROPOSE, ResourceScope(p.tenant_id, case_id))

    # 1. Security Gate & format detection
    det = detect(data, declared_name)
    sha256_hash = hashlib.sha256(data).hexdigest()
    size_bytes = len(data)

    doc_version_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    # 2. Immutable Object Store
    object_store.put(p.tenant_id, data)

    # 3. Synchronous Parser Attempt (async background worker in prod)
    parse_outcome: ParseResult | None = None
    parse_error: str | None = None
    try:
        parse_outcome = parse_bytes(data, declared_name)
    except Exception as e:
        parse_error = str(e)

    doc_status = "FAILED"
    parser_name = "unknown"
    parser_ver = "1.0.0"
    diagnostics = []

    if parse_outcome:
        doc_status = parse_outcome.status
        parser_name = parse_outcome.parser
        parser_ver = parse_outcome.parser_version
        diagnostics = parse_outcome.diagnostics
    elif parse_error:
        diagnostics = [parse_error]

    # 4. Canonical DB Write
    with tenant_tx(p.tenant_id) as c:
        # Check case existence
        case = c.execute("SELECT id, origin FROM cases WHERE id=%s", (case_id,)).fetchone()
        if not case:
            raise NotFound("Case not found")

        # Insert document version
        c.execute(
            "INSERT INTO document_versions("
            "  id, tenant_id, case_id, sha256, size_bytes, declared_name, declared_type, detected_type,"
            "  data_class, status, parser, parser_version, diagnostics, origin, object_stored, submitted_by"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s)",
            (
                doc_version_id,
                p.tenant_id,
                case_id,
                sha256_hash,
                size_bytes,
                declared_name,
                declared_type or det.media_type,
                det.kind,
                data_class,
                doc_status,
                parser_name,
                parser_ver,
                json.dumps(diagnostics),
                origin,
                p.actor_id,
            ),
        )

        # Ingestion job record
        job_state = "SUCCEEDED" if doc_status in ("PARSED", "PARTIAL") else "FAILED"
        c.execute(
            "INSERT INTO ingestion_jobs(id, tenant_id, document_version_id, state, finished_at) "
            "VALUES (%s, %s, %s, %s, clock_timestamp())",
            (job_id, p.tenant_id, doc_version_id, job_state),
        )

        # Insert extracted evidence spans with embeddings
        spans_stored = 0
        if parse_outcome and parse_outcome.spans:
            span_texts = [s.text for s in parse_outcome.spans]
            embeddings = embed_texts(span_texts)

            for idx, s in enumerate(parse_outcome.spans):
                span_id = str(uuid.uuid4())
                text_hash = hashlib.sha256(s.text.encode("utf-8")).hexdigest()
                emb = embeddings[idx] if idx < len(embeddings) else None
                c.execute(
                    "INSERT INTO evidence_spans("
                    "  id, tenant_id, document_version_id, ordinal, locator, text, text_sha256, heading, quality, embedding"
                    ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)",
                    (
                        span_id,
                        p.tenant_id,
                        doc_version_id,
                        s.ordinal,
                        json.dumps(s.locator),
                        s.text,
                        text_hash,
                        s.heading,
                        s.quality,
                        emb,
                    ),
                )
                spans_stored += 1

        # Emit audit & transactional event
        emit_event(
            c,
            p,
            case_id=case_id,
            aggregate_id=doc_version_id,
            revision=1,
            event_type="source.version_captured" if doc_status == "PARSED" else "source.parse_failed",
            payload_refs=[{"kind": "document_version", "id": doc_version_id, "revision": 1}],
            origin=origin,
        )

    return {
        "document_version_id": doc_version_id,
        "job_id": job_id,
        "sha256": sha256_hash,
        "size_bytes": size_bytes,
        "status": doc_status,
        "spans_count": spans_stored,
        "diagnostics": diagnostics,
    }


def link_claim_evidence(
    p: Principal,
    claim_id: str,
    revision: int,
    evidence_span_id: str,
    quote: str | None = None,
    support_type: str = "DIRECT",
) -> None:
    """Link an accepted or proposed claim to an exact evidence span in the same tenant (SRS-011, SRS-016)."""
    with tenant_tx(p.tenant_id) as c:
        # Check claim existence
        cl = c.execute(
            "SELECT case_id FROM claim_revisions WHERE claim_id=%s AND revision=%s",
            (claim_id, revision),
        ).fetchone()
        if not cl:
            raise NotFound("Claim revision not found")
        authorize(p, Op.PROPOSE, ResourceScope(p.tenant_id, str(cl["case_id"])))

        # Check evidence span existence
        span = c.execute("SELECT id FROM evidence_spans WHERE id=%s", (evidence_span_id,)).fetchone()
        if not span:
            raise NotFound("Evidence span not found in tenant scope")

        c.execute(
            "INSERT INTO claim_evidence(tenant_id, claim_id, revision, evidence_span_id, quote, support_type) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (p.tenant_id, claim_id, revision, evidence_span_id, quote, support_type),
        )
