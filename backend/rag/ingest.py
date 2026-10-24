"""
Document ingestion pipeline.

Flow:
  raw file → parse → chunk → embed → store in ChromaDB + SQLite

Supports: PDF, DOCX, CSV, plain text.
"""
from __future__ import annotations
import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from config import settings as cfg

logger = logging.getLogger(__name__)

# ── Embedding model (local, no API key needed) ────────────────────────────────
_embedder: Optional[SentenceTransformer] = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        logger.info(f"Loading embedding model: {cfg.embedding_model}")
        _embedder = SentenceTransformer(cfg.embedding_model)
    return _embedder


# ── ChromaDB client ───────────────────────────────────────────────────────────
_chroma_client: Optional[chromadb.PersistentClient] = None


def get_chroma_client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        persist = Path(cfg.chroma_persist_dir).resolve()
        persist.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=str(persist),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _chroma_client


def get_collection(case_id: str) -> chromadb.Collection:
    """Return (or create) a ChromaDB collection scoped to a case."""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", case_id)
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=f"case_{safe_id}",
        metadata={"hnsw:space": "cosine"},
    )


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text(file_path: Path) -> str:
    file_path = Path(file_path).resolve()
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(file_path)
    elif suffix in (".docx", ".doc"):
        return _extract_docx(file_path)
    elif suffix == ".csv":
        return _extract_csv(file_path)
    else:
        return file_path.read_text(encoding="utf-8", errors="ignore")


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        texts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                texts.append(t)
        return "\n\n".join(texts)
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""


def _extract_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        logger.error(f"DOCX extraction failed: {e}")
        return ""


def _extract_csv(path: Path) -> str:
    try:
        import pandas as pd
        df = pd.read_csv(path)
        return df.to_string(index=False)
    except Exception as e:
        logger.error(f"CSV extraction failed: {e}")
        return path.read_text(encoding="utf-8", errors="ignore")


# ── Chunking ─────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 400, overlap: int = 80) -> list[str]:
    """Split text into overlapping chunks of roughly chunk_size characters."""
    if not text.strip():
        return []
    # Split on sentence boundaries first
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = []
    current_len = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if current_len + len(sentence) > chunk_size and current:
            chunk = " ".join(current)
            chunks.append(chunk)
            # Keep last sentence for overlap
            words = chunk.split()
            overlap_words = words[-overlap // 6 :] if overlap else []
            current = [" ".join(overlap_words), sentence] if overlap_words else [sentence]
            current_len = sum(len(s) for s in current)
        else:
            current.append(sentence)
            current_len += len(sentence)

    if current:
        chunks.append(" ".join(current))

    return [c for c in chunks if len(c.strip()) > 30]


# ── Ingest ────────────────────────────────────────────────────────────────────

def ingest_document(file_path: Path, case_id: str, source_name: str) -> dict:
    """
    Parse, chunk, embed and store a document.
    Returns: {doc_id, chunk_count, text_preview}
    """
    text = extract_text(file_path)
    if not text.strip():
        raise ValueError(f"Could not extract any text from {file_path.name}")

    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("Document produced no usable chunks")

    embedder = get_embedder()
    collection = get_collection(case_id)

    embeddings = embedder.encode(chunks, show_progress_bar=False).tolist()
    # A case can contain two files with identical text. Keep their chunks and
    # provenance separate so removing either file only removes its own spans.
    doc_id = hashlib.sha256(f"{source_name}\0{text}".encode()).hexdigest()[:16]

    ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": source_name, "chunk_index": i, "doc_id": doc_id} for i in range(len(chunks))]

    collection.add(documents=chunks, embeddings=embeddings, ids=ids, metadatas=metadatas)

    logger.info(f"Ingested {source_name}: {len(chunks)} chunks → ChromaDB collection case_{case_id}")
    return {
        "doc_id": doc_id,
        "chunk_count": len(chunks),
        "text_preview": text[:500],
    }


def ingest_text(text: str, case_id: str, source_name: str) -> dict:
    """Ingest arbitrary text (e.g., web page content) into the RAG store."""
    chunks = chunk_text(text)
    if not chunks:
        return {"doc_id": "empty", "chunk_count": 0, "text_preview": ""}

    embedder = get_embedder()
    collection = get_collection(case_id)

    embeddings = embedder.encode(chunks, show_progress_bar=False).tolist()
    doc_id = hashlib.sha256(text.encode()).hexdigest()[:16]

    ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": source_name, "chunk_index": i, "doc_id": doc_id} for i in range(len(chunks))]

    try:
        collection.add(documents=chunks, embeddings=embeddings, ids=ids, metadatas=metadatas)
    except Exception:
        # Might already exist — try upsert
        collection.upsert(documents=chunks, embeddings=embeddings, ids=ids, metadatas=metadatas)

    return {"doc_id": doc_id, "chunk_count": len(chunks), "text_preview": text[:200]}


def attach_document_to_case(doc_key: str, case_id: str) -> int:
    """
    Copy an uploaded document's chunks (stored under its doc key) into the case's
    collection, so every agent retrieving by case_id sees the company document.
    Returns the number of chunks copied.
    """
    src = get_collection(doc_key)
    data = src.get(include=["documents", "embeddings", "metadatas"])
    ids = data.get("ids") or []
    if not ids:
        return 0
    get_collection(case_id).upsert(
        ids=ids,
        documents=data["documents"],
        embeddings=data["embeddings"],
        metadatas=data["metadatas"],
    )
    return len(ids)
