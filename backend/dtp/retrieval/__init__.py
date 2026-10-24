"""dtp.retrieval package initialization."""
from .embeddings import embed_query, embed_texts
from .service import EvidencePack, RetrievedSpan, compute_rrf, hybrid_search

__all__ = ["embed_texts", "embed_query", "compute_rrf", "hybrid_search", "RetrievedSpan", "EvidencePack"]
