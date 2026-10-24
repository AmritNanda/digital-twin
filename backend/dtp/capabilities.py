"""Capability status reporting (SRS-002/051, AI contract §5).

Distinguishes: IMPLEMENTED, UNCONFIGURED (needs credentials/access), NOT_IMPLEMENTED.
Never prints secret values; diagnostics list variable NAMES only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    id: str
    description: str
    required_env: tuple[str, ...]
    implemented: bool


# Only integrations with a real adapter are marked implemented=True.
CATALOG: tuple[Capability, ...] = (
    Capability("llm.openai_compatible", "LLM via OpenAI-compatible endpoint (legacy MVP adapter)",
               ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"), True),
    Capability("search.tavily", "Tavily web search (legacy MVP adapter)", ("TAVILY_API_KEY",), True),
    Capability("db.postgres", "Canonical PostgreSQL store", ("DATABASE_URL",), False),
    Capability("graph.neo4j", "Neo4j projection", ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"), False),
    Capability("object.storage", "Versioned private object storage", ("OBJECT_STORE_URI",), False),
    Capability("identity.oidc", "OIDC identity provider", ("OIDC_ISSUER", "OIDC_CLIENT_ID"), False),
)


def status(env: dict[str, str] | None = None) -> list[dict]:
    env = os.environ if env is None else env
    out = []
    for c in CATALOG:
        missing = [k for k in c.required_env if not env.get(k, "").strip()]
        if not c.implemented:
            state = "NOT_IMPLEMENTED"
        elif missing:
            state = "UNCONFIGURED"
        else:
            state = "CONFIGURED_UNVERIFIED"  # configured != live-verified (needs sandbox test)
        out.append({"id": c.id, "state": state, "description": c.description,
                    "missing_env": missing})
    return out
