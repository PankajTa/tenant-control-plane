"""Consumer resilience: poison messages, transient failures, idempotent redelivery."""

import json

from sqlalchemy.exc import OperationalError

from controlplane.messaging.consumer import Disposition, UpdateConsumer
from controlplane.services.updates import Outcome, UpdateResult, apply_update


def body(**kw) -> bytes:
    return json.dumps(kw).encode()


def make(session_factory, settings, apply_fn=apply_update):
    return UpdateConsumer(session_factory, settings, apply_fn=apply_fn)


def test_valid_update_is_acked_and_applied(tenants, session_factory, settings):
    tenant, task = tenants.create_tenant("acme", "Acme")
    c = make(session_factory, settings)
    assert c.process(body(update_id="u1", task_id=task.id, status="in_progress")) == Disposition.ACK
    assert c.process(body(update_id="u2", task_id=task.id, status="done")) == Disposition.ACK
    assert tenants.get_tenant(tenant.id).status == "active"


def test_redelivery_is_acked_and_harmless(tenants, session_factory, settings):
    tenant, task = tenants.create_tenant("acme", "Acme")
    c = make(session_factory, settings)
    msg = body(update_id="u1", task_id=task.id, status="done")
    assert c.process(msg) == Disposition.ACK
    version = tenants.get_tenant(tenant.id).version
    assert c.process(msg) == Disposition.ACK
    assert tenants.get_tenant(tenant.id).version == version


def test_poison_messages_are_dead_lettered(tenants, session_factory, settings):
    c = make(session_factory, settings)
    for poison in [
        b"not json at all",
        b"{}",
        b"[]",
        body(update_id="u", task_id="t", status="accepted"),  # not a legal worker status
        body(update_id="", task_id="t", status="done"),
        body(update_id="u", task_id="no-such-task", status="done"),  # unknown task
    ]:
        assert c.process(poison) == Disposition.DEAD_LETTER, poison


def test_unexpected_exception_is_dead_lettered_not_fatal(session_factory, settings):
    def boom(*_):
        raise RuntimeError("bug")

    c = make(session_factory, settings, boom)
    assert c.process(body(update_id="u", task_id="t", status="done")) == Disposition.DEAD_LETTER


def _db_error():
    return OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_transient_db_errors_are_retried_then_succeed(session_factory, settings):
    calls = {"n": 0}

    def flaky(sf, msg):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _db_error()
        return UpdateResult(Outcome.APPLIED, "done")

    c = make(session_factory, settings, flaky)  # max_attempts=3 in the fixture
    assert c.process(body(update_id="u", task_id="t", status="done")) == Disposition.ACK
    assert calls["n"] == 3


def test_persistent_transient_failure_requeues_instead_of_losing(session_factory, settings):
    def down(sf, msg):
        raise _db_error()

    c = make(session_factory, settings, down)
    assert c.process(body(update_id="u", task_id="t", status="done")) == Disposition.REQUEUE
