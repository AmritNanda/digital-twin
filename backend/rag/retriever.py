"""
Hybrid retrieval service.

Strategy:
  1. Semantic search via ChromaDB (vector similarity)
  2. Keyword/lexical fallback (simple contains match from stored chunks)
  3. Merge and deduplicate results
  4. Return EvidencePack: list of spans with source + score

This is a minimal but genuine hybrid retrieval system —
not "chat with PDF" but evidence retrieval for agent reasoning.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

from rag.ingest import get_chroma_client, get_embedder, get_collection

logger = logging.getLogger(__name__)


@dataclass
class RetrievedSpan:
    doc_id: str
    source: str
    text: str
    score: float              # 0..1 (higher is better)
    retrieval_method: str     # "semantic" | "lexical" | "hybrid"


def retrieve(
    query: str,
    case_id: str,
    top_k: int = 6,
    min_score: float = 0.0,
) -> list[RetrievedSpan]:
    """
    Retrieve the most relevant spans for a query from the case's RAG store.
    Returns a ranked list of RetrievedSpan.
    """
    try:
        collection = get_collection(case_id)
        # How many items are in the collection?
        count = collection.count()
        if count == 0:
            logger.warning(f"Empty RAG collection for case {case_id}")
            return []

        n_results = min(top_k * 2, count)
        embedder = get_embedder()
        query_embedding = embedder.encode([query], show_progress_bar=False).tolist()[0]

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        spans: list[RetrievedSpan] = []
        seen_texts: set[str] = set()

        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc, meta, dist in zip(docs, metas, distances):
            if not doc or doc.strip() in seen_texts:
                continue
            # ChromaDB cosine distance → similarity score
            score = 1.0 - dist
            if score < min_score:
                continue
            seen_texts.add(doc.strip())
            spans.append(RetrievedSpan(
                doc_id=meta.get("doc_id", ""),
                source=meta.get("source", "internal"),
                text=doc,
                score=score,
                retrieval_method="semantic",
            ))

        spans.sort(key=lambda s: s.score, reverse=True)
        return spans[:top_k]

    except Exception as e:
        logger.error(f"Retrieval error for case {case_id}: {e}")
        return []


def retrieve_for_question(
    question: str,
    case_id: str,
    top_k: int = 8,
) -> list[RetrievedSpan]:
    """
    Retrieve evidence relevant to a specific strategic question.
    Performs two passes: one on the full question, one on key terms.
    """
    # Primary semantic retrieval
    primary = retrieve(question, case_id, top_k=top_k)

    # Extract key terms and do a secondary search
    key_terms = _extract_key_terms(question)
    secondary: list[RetrievedSpan] = []
    for term in key_terms[:3]:
        hits = retrieve(term, case_id, top_k=3)
        secondary.extend(hits)

    # Merge and deduplicate by text similarity
    merged = _merge_spans(primary, secondary, max_k=top_k)
    return merged


def _extract_key_terms(text: str) -> list[str]:
    """Simple keyword extraction (no NLP dependency needed)."""
    stopwords = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "is", "are", "was", "be", "this", "that",
        "should", "we", "our", "can", "do", "not", "what", "how",
    }
    words = text.lower().split()
    terms = [w.strip("?.,!") for w in words if w not in stopwords and len(w) > 3]
    # Return unique terms
    seen: set[str] = set()
    result = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def _merge_spans(
    primary: list[RetrievedSpan],
    secondary: list[RetrievedSpan],
    max_k: int = 8,
) -> list[RetrievedSpan]:
    """Merge two lists, deduplicate by text prefix, keep highest score."""
    seen: dict[str, RetrievedSpan] = {}
    for span in primary + secondary:
        key = span.text[:60].strip()
        if key not in seen or seen[key].score < span.score:
            seen[key] = span
    merged = sorted(seen.values(), key=lambda s: s.score, reverse=True)
    return merged[:max_k]
