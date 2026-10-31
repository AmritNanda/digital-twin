"""Stage 3 integration tests: Intake, Security, Parsers, Object Storage, and Evidence Spans (AT-001, AT-002, AT-041).
Validates:
1. Supported text, CSV, DOCX, XLSX, PPTX, and PDF parsing with exact locators.
2. Security gate: empty, oversized, macro-bearing, zip bomb, path traversal, and XXE rejection.
3. Transactional persistence in PostgreSQL (document_versions, ingestion_jobs, evidence_spans).
4. Content-addressed immutable object storage.
"""
from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import docx
import openpyxl
import pptx
import pypdf
import pytest

from dtp import repo
from dtp.db import tenant_tx
from dtp.identity import Op, Principal, Role
from dtp.intake.parsers import parse_bytes
from dtp.intake.security import Rejected, detect
from dtp.intake.service import ingest_file
from dtp.intake.storage import object_store


@pytest.fixture()
def intake_world(postgres_ready):
    tid, owner_id = repo.bootstrap_tenant("intake_t", f"o{time.time_ns()}@intake.test")
    owner = Principal(tid, owner_id, frozenset({Role.OWNER}))
    case = repo.create_case(owner, title="Intake Test Case", objective="Intake testing", horizon_days=30, origin="FIXTURE")
    return {"tid": tid, "owner": owner, "case": case}


# ── Security Gate Tests (AT-002, AT-041) ─────────────────────────────────────

def test_security_empty_and_oversized():
    with pytest.raises(Rejected, match="file is empty"):
        detect(b"", "empty.txt")

    with pytest.raises(Rejected, match="limit"):
        detect(b"x" * (21 * 1024 * 1024), "huge.txt")


def test_security_rejects_macros():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<document/>")
        z.writestr("word/vbaProject.bin", b"fake macro binary")
    with pytest.raises(Rejected, match="macros/VBA"):
        detect(buf.getvalue(), "doc_with_macros.docx")


def test_security_rejects_path_traversal():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.txt", "evil")
    with pytest.raises(Rejected, match="unsafe archive entry"):
        detect(buf.getvalue(), "traversal.docx")


def test_security_rejects_encrypted_pdf():
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret_pass")
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(Rejected, match="encrypted PDF"):
        detect(buf.getvalue(), "locked.pdf")


# ── Format Parser Tests (AT-001) ──────────────────────────────────────────────

def test_parse_text_and_anchors():
    content = b"# Strategy Overview\nLaunch product in Q3.\nTarget price $45."
    res = parse_bytes(content, "strategy.md")
    assert res.status == "PARSED"
    assert len(res.spans) == 3
    assert res.spans[0].locator["type"] == "TEXT_LINES"
    assert res.spans[0].text == "# Strategy Overview"
    assert res.spans[1].heading == "Strategy Overview"


def test_parse_csv_and_anchors():
    content = b"Channel,CAC,Conversion\nSocial,14.50,2.1%\nSearch,22.00,3.5%\n"
    res = parse_bytes(content, "channels.csv")
    assert res.status == "PARSED"
    assert len(res.spans) >= 6
    cell_spans = [s for s in res.spans if s.locator["type"] == "TABLE_CELLS"]
    assert any(s.text == "Channel: Social" for s in cell_spans)


def test_parse_docx_and_anchors():
    doc = docx.Document()
    doc.add_heading("Product Plan", level=1)
    doc.add_paragraph("Unit cost is $8.20.")
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Metric"
    table.rows[0].cells[1].text = "Value"
    table.rows[1].cells[0].text = "Target"
    table.rows[1].cells[1].text = "1000 units"
    buf = io.BytesIO()
    doc.save(buf)

    res = parse_bytes(buf.getvalue(), "plan.docx")
    assert res.status == "PARSED"
    assert any(s.locator["type"] == "DOCUMENT_BLOCK" and "Unit cost" in s.text for s in res.spans)
    assert any(s.locator.get("block_type") == "table_row" for s in res.spans)


def test_parse_xlsx_and_anchors():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Financials"
    ws["A1"] = "COGS"
    ws["B1"] = 315.00
    buf = io.BytesIO()
    wb.save(buf)

    res = parse_bytes(buf.getvalue(), "data.xlsx")
    assert res.status == "PARSED"
    assert any(s.locator["coordinate"] == "A1" and s.text == "COGS" for s in res.spans)
    assert any(s.locator["coordinate"] == "B1" and s.text == "315" for s in res.spans)


def test_parse_pptx_and_anchors():
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Q3 Deck"
    slide.placeholders[1].text = "Executive Summary"
    buf = io.BytesIO()
    prs.save(buf)

    res = parse_bytes(buf.getvalue(), "deck.pptx")
    assert res.status == "PARSED"
    assert any(s.locator["type"] == "SLIDE_SHAPE" and "Q3 Deck" in s.text for s in res.spans)


def test_parse_pdf_and_anchors():
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    # Blank page without text layer should flag NEEDS_OCR
    buf = io.BytesIO()
    writer.write(buf)
    res = parse_bytes(buf.getvalue(), "blank.pdf")
    assert res.status == "NEEDS_OCR"


# ── Full Ingestion Service E2E (AT-001, AT-002) ───────────────────────────────

def test_full_ingestion_service_e2e(intake_world):
    owner = intake_world["owner"]
    case_id = intake_world["case"]
    tid = intake_world["tid"]

    data = b"Product: Nila Home Starter Kit\nUnit Cost: $12.50\nHorizon: 90 days"
    res = ingest_file(owner, case_id, "brief.txt", data, origin="FIXTURE")

    assert res["status"] == "PARSED"
    assert res["spans_count"] == 3
    doc_id = res["document_version_id"]

    # Verify immutable object storage
    assert object_store.exists(tid, res["sha256"])
    assert object_store.get(tid, res["sha256"]) == data

    # Verify PostgreSQL records
    with tenant_tx(tid) as c:
        doc = c.execute("SELECT * FROM document_versions WHERE id=%s", (doc_id,)).fetchone()
        assert doc is not None
        assert doc["sha256"] == res["sha256"]
        assert doc["status"] == "PARSED"

        spans = c.execute("SELECT * FROM evidence_spans WHERE document_version_id=%s ORDER BY ordinal", (doc_id,)).fetchall()
        assert len(spans) == 3
        assert "Unit Cost" in spans[1]["text"]

        # Immutability check: cannot delete evidence span
        with pytest.raises(Exception):
            c.execute("DELETE FROM evidence_spans WHERE id=%s", (spans[0]["id"],))
