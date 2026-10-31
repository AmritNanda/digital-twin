"""
FastAPI main server — Agentic Strategic Intelligence System MVP
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, FiniteFloat

from config import settings
from rag.ingest import ingest_document, attach_document_to_case
from agents.graph import run_case
from dtp import capabilities as dtp_capabilities
from dtp.jurisdiction import context_preamble, list_jurisdictions, resolve_context
from dtp.requirements_guide import guide as requirements_guide, scan_text
from workspace_api import router as workspace_router
from workspace_store import initialize as initialize_workspace

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_workspace()
    yield


app = FastAPI(
    title="Agentic Strategic Intelligence System",
    description="Autonomous strategic decision MVP",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(workspace_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("STRATEGY_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()],
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
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


# ── Static files ──────────────────────────────────────────────────────────────
if PUBLIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(PUBLIC_DIR)), name="static")
if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="frontend-assets")


@app.get("/")
def index():
    built_index = FRONTEND_DIST / "index.html"
    if built_index.exists():
        return FileResponse(str(built_index))
    index_file = PUBLIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "Agentic Strategic Intelligence System API"}


# ── Models ────────────────────────────────────────────────────────────────────

class CaseCreate(BaseModel):
    doc_id: Optional[str] = None
    question: str
    # User-chosen operating context; omitted fields default to USA/USD and are flagged DEFAULTED.
    country: Optional[str] = None
    currency: Optional[str] = None
    tax_basis: Optional[str] = None
    tax_notes: Optional[str] = None


class RequirementScan(BaseModel):
    text: str


@app.get("/api/requirements")
def get_requirements():
    """What details the document/prompt should contain (SRS-007/008)."""
    return requirements_guide()


@app.get("/api/jurisdictions")
def get_jurisdictions():
    return {"default": "US", "jurisdictions": list_jurisdictions()}


@app.post("/api/requirements/check")
def check_requirements(body: RequirementScan):
    """Keyword heuristic only; extracts no facts."""
    return scan_text(body.text[:200_000])


@app.get("/api/capabilities")
def get_capabilities():
    return {"capabilities": dtp_capabilities.status()}


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
    try:
        op_ctx = resolve_context(body.country, body.currency, body.tax_basis, body.tax_notes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    question = f"{context_preamble(op_ctx)}\n{question}"
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
        "operating_context": op_ctx,
    }

    # Launch workflow in background (keep a reference until it finishes)
    task = asyncio.create_task(_run_workflow(case_id, question, body.doc_id, q))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

    return {"case_id": case_id, "status": "running", "operating_context": op_ctx}


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


class SimulationApiRequest(BaseModel):
    seed: int = Field(default=42, ge=0, le=2**64 - 1)
    draw_count: int = Field(default=1000, ge=1, le=10000)
    price_mean: FiniteFloat = Field(default=699.0, ge=0)
    price_std: FiniteFloat = Field(default=30.0, gt=0)
    cogs_mean: FiniteFloat = Field(default=315.0, ge=0)
    cogs_std: FiniteFloat = Field(default=15.0, gt=0)


@app.post("/api/simulation/evaluate")
def evaluate_simulation(req: SimulationApiRequest):
    """Executes reproducible Monte Carlo simulation (SRS-035, AT-025)."""
    from backend.dtp.numerical.simulation import (
        DistributionSpec,
        DistributionType,
        MonteCarloSimulator,
        SimulationPlan,
    )
    plan = SimulationPlan(
        plan_id=f"sim-{uuid.uuid4().hex[:8]}",
        seed=req.seed,
        draw_count=req.draw_count,
        distributions=[
            DistributionSpec("price", DistributionType.NORMAL, {"mean": req.price_mean, "std": req.price_std}),
            DistributionSpec("cogs", DistributionType.NORMAL, {"mean": req.cogs_mean, "std": req.cogs_std}),
        ],
    )
    sim = MonteCarloSimulator(plan)
    res = sim.run()
    return res.to_dict()


class CashFlowApiRequest(BaseModel):
    initial_cash: FiniteFloat = Field(default=100000.0, ge=0)
    unit_purchase_cost: FiniteFloat = Field(default=315.0, ge=0)
    unit_selling_price: FiniteFloat = Field(default=699.0, ge=0)
    units_per_period: int = Field(default=300, ge=0)
    total_periods: int = Field(default=3, ge=1, le=120)


@app.post("/api/cashflow/evaluate")
def evaluate_cashflow(req: CashFlowApiRequest):
    """Evaluates multi-period cash flow and liquidity (SRS-033, AT-024)."""
    from decimal import Decimal
    from backend.dtp.numerical.cashflow import CashFlowEngine, PeriodInput

    periods_input = []
    for p in range(req.total_periods):
        periods_input.append(
            PeriodInput(
                period=p,
                demand_units=req.units_per_period,
                procurement_receipt_units=req.units_per_period * req.total_periods if p == 0 else 0,
                procurement_order_units=req.units_per_period * req.total_periods if p == 0 else 0,
                unit_purchase_cost=Decimal(str(req.unit_purchase_cost)),
                unit_selling_price=Decimal(str(req.unit_selling_price)),
                unit_cogs=Decimal(str(req.unit_purchase_cost)),
                unit_fulfillment=Decimal("60.00"),
                payment_fee_rate=Decimal("0.03"),
                acquisition_cost_per_unit=Decimal("140.00"),
                fixed_operating_costs=Decimal("40000.00"),
            )
        )

    engine = CashFlowEngine(
        currency="USD",
        initial_cash=Decimal(str(req.initial_cash)),
        initial_inventory=0,
        min_cash_reserve=Decimal("10000.00"),
    )
    res = engine.run(periods_input)
    return res.to_dict()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.port,
        app_dir=str(Path(__file__).resolve().parent),
        reload=False,
        log_level="info",
    )
