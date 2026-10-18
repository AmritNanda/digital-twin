"""
FastAPI main server — Agentic Strategic Intelligence System MVP
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from rag.ingest import ingest_document, attach_document_to_case
from agents.graph import run_case

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Agentic Strategic Intelligence System",
    description="Autonomous strategic decision MVP",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory case store (use Redis/DB in production)
_cases: dict[str, dict] = {}
_events: dict[str, asyncio.Queue] = {}
_tasks: set[asyncio.Task] = set()   # strong refs so background tasks aren't GC'd

ALLOWED_SUFFIXES = {".pdf", ".csv", ".txt", ".md", ".docx"}

UPLOAD_DIR = Path(settings.upload_dir).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

PUBLIC_DIR = Path(__file__).parent.parent / "public"


# ── Static files ──────────────────────────────────────────────────────────────
if PUBLIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(PUBLIC_DIR)), name="static")


@app.get("/")
def index():
    index_file = PUBLIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "Agentic Strategic Intelligence System API"}


# ── Models ────────────────────────────────────────────────────────────────────

class CaseCreate(BaseModel):
    doc_id: Optional[str] = None
    question: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload and ingest a company document into the RAG store."""
    if file.size and file.size > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(413, "File too large")

    doc_id = str(uuid.uuid4())[:12]
    suffix = Path(file.filename or "file.txt").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, f"Unsupported file type '{suffix}'. Use PDF, CSV, TXT, MD or DOCX.")
    file_path = UPLOAD_DIR / f"{doc_id}{suffix}"

    # Write file
    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(413, "File too large")
    file_path.write_bytes(content)

    # Ingest into RAG (uses doc_id as collection key). Embedding is blocking → thread.
    try:
        result = await asyncio.to_thread(
            ingest_document, file_path, doc_id, file.filename or "uploaded_document"
        )
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(422, f"Could not process document: {e}")

    logger.info(f"Document {doc_id} ingested: {result['chunk_count']} chunks")
    return {
        "doc_id": doc_id,
        "filename": file.filename,
        "chunks": result["chunk_count"],
        "preview": result["text_preview"][:300],
    }


@app.post("/api/case")
async def create_case(body: CaseCreate):
    """Create a decision case and start the agentic workflow."""
    question = body.question.strip()
    if len(question) < 10:
        raise HTTPException(400, "Please provide a more detailed strategic question.")
    if not settings.llm_configured:
        raise HTTPException(
            400,
            "LLM_API_KEY is not configured. Add it to .env (see .env.example) and restart the server.",
        )

    case_id = str(uuid.uuid4())[:12]

    # Make the uploaded document visible to agents (they retrieve by case_id)
    if body.doc_id:
        try:
            copied = await asyncio.to_thread(attach_document_to_case, body.doc_id, case_id)
            logger.info(f"Case {case_id}: attached document {body.doc_id} ({copied} chunks)")
        except Exception as e:
            logger.error(f"Could not attach document {body.doc_id}: {e}")
            raise HTTPException(404, f"Document {body.doc_id} not found or unreadable")

    q = asyncio.Queue()
    _events[case_id] = q

    _cases[case_id] = {
        "case_id": case_id,
        "question": question,
        "doc_id": body.doc_id,
        "status": "running",
        "result": None,
    }

    # Launch workflow in background (keep a reference until it finishes)
    task = asyncio.create_task(_run_workflow(case_id, question, body.doc_id, q))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

    return {"case_id": case_id, "status": "running"}


async def _run_workflow(case_id: str, question: str, doc_id: Optional[str], q: asyncio.Queue):
    """Background task: run the full agentic graph and push events to the queue."""
    async def push_event(event: dict):
        await q.put({"data": event})

    try:
        result = await asyncio.wait_for(
            run_case(case_id, question, doc_id, push_event),
            timeout=settings.case_timeout_seconds,
        )
        failed = bool(result.get("error"))
        _cases[case_id]["status"] = "failed" if failed else "completed"
        _cases[case_id]["result"] = result
        await q.put({"data": {"type": "done", "result": result}})
    except asyncio.TimeoutError:
        msg = f"Case timed out after {settings.case_timeout_seconds}s"
        logger.error(f"Case {case_id}: {msg}")
        _cases[case_id]["status"] = "failed"
        await q.put({"data": {"type": "error", "message": msg}})
    except Exception as e:
        logger.error(f"Case {case_id} workflow error: {e}", exc_info=True)
        _cases[case_id]["status"] = "failed"
        await q.put({"data": {"type": "error", "message": str(e)}})
    finally:
        await q.put(None)  # Sentinel: stream ended


@app.get("/api/case/{case_id}/stream")
async def stream_events(case_id: str):
    """SSE stream of agent events for a case."""
    if case_id not in _events:
        raise HTTPException(404, "Case not found")

    q = _events[case_id]

    async def generate():
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=15.0)
            except asyncio.TimeoutError:
                # Comment line keeps proxies/browsers from closing an idle connection
                # while a slow LLM call is in progress.
                yield ": keepalive\n\n"
                continue
            if item is None:
                yield "event: done\ndata: {}\n\n"
                break
            data = json.dumps(item["data"], default=str)
            yield f"event: agent\ndata: {data}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/case/{case_id}/result")
def get_result(case_id: str):
    """Get the final decision package."""
    case = _cases.get(case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return case


@app.get("/api/case/{case_id}/status")
def get_status(case_id: str):
    """Get case status."""
    case = _cases.get(case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return {"case_id": case_id, "status": case["status"]}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "llm_configured": settings.llm_configured,
        "llm_model": settings.llm_model,
        "embedding_model": settings.embedding_model,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
        log_level="info",
    )
