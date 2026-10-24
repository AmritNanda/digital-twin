"""Structural contract validation (Annex C). Schema validity != semantic validity."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

_DIR = Path(__file__).parent
ARTIFACT_TYPES = (
    "ClaimProposal", "ParameterProposal", "TaskRequest", "AgentResult", "EventEnvelope",
    "Challenge", "ScenarioPatch", "SimulationResult", "DecisionProposal",
    "ApprovalRecord", "VerificationReport",
)


class ContractError(ValueError):
    """Malformed transport payload."""

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or []


def _reject_constant(name: str):
    raise ContractError(f"non-finite JSON constant rejected: {name}")


def strict_loads(text: str | bytes) -> Any:
    """Parse JSON rejecting NaN/Infinity and duplicate keys."""

    def _pairs(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise ContractError(f"duplicate JSON key: {k}")
            d[k] = v
        return d

    try:
        return json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_pairs)
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON: {exc}") from exc


@lru_cache(maxsize=1)
def _root() -> dict:
    return json.loads((_DIR / "core.schema.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _validator(artifact_type: str) -> Draft202012Validator:
    if artifact_type not in ARTIFACT_TYPES:
        raise ContractError(f"unknown artifact_type: {artifact_type!r}")
    root = _root()
    schema = {"$schema": root["$schema"], "$defs": root["$defs"], "$ref": f"#/$defs/{artifact_type}"}
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_artifact(payload: dict) -> None:
    """Raise ContractError unless payload matches its declared core schema."""
    if not isinstance(payload, dict) or "artifact_type" not in payload:
        raise ContractError("payload must be an object with artifact_type")
    v = _validator(payload["artifact_type"])
    errs = sorted(v.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errs:
        raise ContractError(
            f"{payload['artifact_type']} failed schema validation",
            [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errs],
        )


def load_fixture_examples() -> list[dict]:
    """FIXTURE structural examples only; never a connected dataset."""
    data = json.loads((_DIR / "examples.json").read_text(encoding="utf-8"))
    assert data.get("fixture_only") is True
    return data["artifacts"]
