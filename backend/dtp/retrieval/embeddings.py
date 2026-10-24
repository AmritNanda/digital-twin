"""Local vector embeddings service using SentenceTransformers (SRS-018, AT-009).
Runs local `all-MiniLM-L6-v2` (384 dims) without requiring external third-party API keys.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Sequence

from sentence_transformers import SentenceTransformer

DEFAULT_EMBED_MODEL = "all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def _get_model(model_name: str = DEFAULT_EMBED_MODEL) -> SentenceTransformer:
    return SentenceTransformer(model_name)


def embed_texts(texts: Sequence[str], model_name: str = DEFAULT_EMBED_MODEL) -> list[list[float]]:
    """Generate dense 384-dimensional vector embeddings."""
    if not texts:
        return []
    model = _get_model(model_name)
    embeddings = model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
    return [e.tolist() for e in embeddings]


def embed_query(query: str, model_name: str = DEFAULT_EMBED_MODEL) -> list[float]:
    return embed_texts([query], model_name)[0]
