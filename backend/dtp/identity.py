"""Identity, tenancy and the D2 permission matrix (SRS-004, AT-006, AT-038).

Tenant/actor come ONLY from server-authenticated context (`Principal`). IDs in
payloads are lookup inputs, never authority. Cross-tenant access is reported as
NotFound so existence is not leaked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    OWNER = "owner"
    ANALYST = "analyst"
    DOMAIN_REVIEWER = "domain_reviewer"
    RESEARCH_OPERATOR = "research_operator"
    ADMINISTRATOR = "administrator"
    READER = "reader"


class Op(str, Enum):
    READ = "read"
    REVISE_OBJECTIVES = "revise_objectives"
    PROPOSE = "propose"
    ACCEPT = "accept"
    SET_ENVELOPE = "set_envelope"
    APPROVE_ACTION = "approve_action"
    CONFIGURE_SOURCES = "configure_sources"
    MANAGE_DEPLOYMENT = "manage_deployment"
    EXPORT_DELETE = "export_delete"


# value: "Y" unconditional within tenant/case; "G" needs explicit grant (category/scope);
# "A" assigned scope only; absent => deny. Mirrors SRS Annex D2.
_M: dict[Role, dict[Op, str]] = {
    Role.OWNER: {Op.READ: "Y", Op.REVISE_OBJECTIVES: "Y", Op.PROPOSE: "Y", Op.ACCEPT: "G",
                 Op.SET_ENVELOPE: "Y", Op.APPROVE_ACTION: "G", Op.CONFIGURE_SOURCES: "Y",
                 Op.MANAGE_DEPLOYMENT: "Y", Op.EXPORT_DELETE: "G"},
    Role.ANALYST: {Op.READ: "Y", Op.PROPOSE: "Y", Op.ACCEPT: "G", Op.EXPORT_DELETE: "G"},
    Role.DOMAIN_REVIEWER: {Op.READ: "A", Op.PROPOSE: "A", Op.ACCEPT: "A",
                           Op.APPROVE_ACTION: "G", Op.EXPORT_DELETE: "G"},
    Role.RESEARCH_OPERATOR: {Op.READ: "A", Op.PROPOSE: "A", Op.CONFIGURE_SOURCES: "A"},
    Role.ADMINISTRATOR: {Op.READ: "G", Op.CONFIGURE_SOURCES: "G", Op.MANAGE_DEPLOYMENT: "A"},
    Role.READER: {Op.READ: "A", Op.EXPORT_DELETE: "G"},
}

# Operations where "propose-only" is stated for analyst/reviewer: REVISE_OBJECTIVES is
# deliberately denied to everyone but the owner here; proposals go through PROPOSE.


class AuthorizationError(Exception):
    pass


class NotFound(Exception):
    """Also used for cross-tenant references (no existence leak)."""


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    actor_id: str
    roles: frozenset[Role]
    case_ids: frozenset[str] = frozenset()          # assigned scope for "A" grants
    grants: frozenset[tuple[Op, str]] = frozenset()  # (op, category) explicit grants
    denies: frozenset[tuple[Op, str]] = frozenset()  # explicit deny overrides broad role
    revoked: bool = False


@dataclass(frozen=True)
class ResourceScope:
    tenant_id: str
    case_id: str | None = None
    category: str = "*"


def authorize(p: Principal, op: Op, res: ResourceScope) -> None:
    """Raise unless allowed. Tenant mismatch => NotFound; role/grant failure => AuthorizationError."""
    if p.revoked:
        raise AuthorizationError("session revoked")
    if p.tenant_id != res.tenant_id:
        raise NotFound("resource not found")
    if (op, res.category) in p.denies or (op, "*") in p.denies:
        raise AuthorizationError("explicit deny")
    for role in p.roles:
        mode = _M.get(role, {}).get(op)
        if mode == "Y":
            return
        if mode == "A" and res.case_id is not None and res.case_id in p.case_ids:
            if op != Op.ACCEPT or (op, res.category) in p.grants:
                return
        if mode == "A" and op == Op.ACCEPT and (op, res.category) in p.grants:
            return
        if mode == "G" and ((op, res.category) in p.grants or (op, "*") in p.grants):
            return
    raise AuthorizationError(f"{op.value} not permitted for role(s) "
                             f"{sorted(r.value for r in p.roles)} on category {res.category}")


def require_independent_review(proposer_actor: str, reviewer_actor: str, *,
                               self_review_allowed: bool = False) -> dict:
    """Proposer/reviewer separation; self-review is recorded, never called independent."""
    same = proposer_actor == reviewer_actor
    if same and not self_review_allowed:
        raise AuthorizationError("policy requires separate proposer and reviewer")
    return {"independent": not same, "self_review_recorded": same}


@dataclass
class DevSession:
    """Dev-only loopback profile (SRS-004): unpredictable token, mutation requires it."""
    token: str
    principal: Principal
    allowed_origins: frozenset[str] = field(default_factory=lambda: frozenset(
        {"http://localhost:8000", "http://127.0.0.1:8000"}))

    def check(self, presented_token: str | None, origin: str | None, client_host: str | None) -> Principal:
        import hmac
        if client_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
            raise AuthorizationError("dev profile is loopback-only")
        if origin is not None and origin not in self.allowed_origins:
            raise AuthorizationError("untrusted origin")
        if not presented_token or not hmac.compare_digest(presented_token, self.token):
            raise AuthorizationError("unauthenticated")
        return self.principal
