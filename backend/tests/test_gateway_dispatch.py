"""An already claimed external action must not be sent twice."""

from contextlib import nullcontext
from datetime import datetime, timezone

from backend.dtp.gateway import service
from backend.dtp.identity import Op, Principal, Role


def test_action_is_claimed_before_external_call_and_not_repeated(monkeypatch):
    principal = Principal("tenant", "owner", frozenset({Role.OWNER}),
                          grants=frozenset({(Op.APPROVE_ACTION, "SEND")}))
    payload = {"message": "send once"}
    now = datetime.now(timezone.utc)
    row = {"id": "action", "tenant_id": "tenant", "case_id": "case", "action_type": "SEND",
           "payload": payload, "approval_hash": service.ActionGateway.compute_approval_hash(payload),
           "idempotency_key": "key", "status": "PENDING", "execution_receipt": None,
           "created_at": now, "executed_at": None}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def cursor(self):
            return self

        def execute(self, query, params):
            if query.lstrip().startswith("SELECT"):
                self.result = row.copy()
            elif "RETURNING executed_at" in query:
                assert row["status"] == "DISPATCHING"
                row["status"], row["execution_receipt"], row["executed_at"] = params[0], params[1], now
                self.result = {"executed_at": now}
            else:
                row["status"] = params[0]
            return self

        def fetchone(self):
            return self.result

    cursor = Cursor()
    monkeypatch.setattr(service, "tenant_tx", lambda _: nullcontext(cursor))
    gateway = service.ActionGateway()
    calls = []

    def send(_):
        assert row["status"] == "DISPATCHING"
        calls.append(1)
        return "SUCCESS", {"sent": True}

    assert gateway.execute_action(principal, "action", payload, send).status == service.ActionStatus.EXECUTED
    assert gateway.execute_action(principal, "action", payload, send).status == service.ActionStatus.EXECUTED
    assert len(calls) == 1
