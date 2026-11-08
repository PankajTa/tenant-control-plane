"""Outbound path: events are published after commit, once, and survive broker outages."""

import json

import pytest

from controlplane.errors import TenantAlreadyExists
from controlplane.messaging.publisher import PublishError
from controlplane.models import Task


def test_nothing_published_until_relay_runs_and_commit_is_visible(tenants, relay, publisher):
    tenant, task = tenants.create_tenant("acme", "Acme")
    assert publisher.published == []  # the API call itself never talks to the broker
    assert relay.run_once() == 1
    key, body, message_id = publisher.published[0]
    event = json.loads(body)
    assert key == "task.created" and message_id == task.id
    assert event["id"] == task.id  # task id doubles as event id
    assert (event["type"], event["tenant_id"], event["status"]) == ("deploy", tenant.id, "accepted")


def test_exactly_one_event_per_state_changing_call(tenants, relay, publisher, session_factory):
    from conftest import drive

    tenant, task = tenants.create_tenant("acme", "Acme")
    drive(session_factory, task.id)
    t = tenants.get_tenant(tenant.id)
    tenants.update_tenant(t.id, t.version, "x")
    relay.run_once()
    assert len(publisher.published) == 2  # deploy + update
    assert relay.run_once() == 0  # nothing re-sent
    assert len(publisher.published) == 2


def test_rollback_publishes_nothing(tenants, relay, publisher):
    tenants.create_tenant("acme", "Acme")
    relay.run_once()
    with pytest.raises(TenantAlreadyExists):
        tenants.create_tenant("acme", "Again")  # rolled back
    assert relay.run_once() == 0
    assert len(publisher.published) == 1


def test_broker_outage_keeps_events_for_retry(tenants, relay, publisher, session_factory):
    tenant, task = tenants.create_tenant("acme", "Acme")
    publisher.fail_next = 1
    with pytest.raises(PublishError):
        relay.run_once()
    with session_factory() as s:
        assert s.get(Task, task.id).published_at is None  # still pending, not lost
    assert relay.run_once() == 1  # next attempt succeeds
    assert len(publisher.published) == 1


def test_partial_batch_failure_does_not_resend_what_succeeded(tenants, relay, publisher):
    for i in range(3):
        tenants.create_tenant(f"tenant-{i}", "T")
    publisher.fail_next = 0

    calls = {"n": 0}
    original = publisher.publish

    def flaky(routing_key, body, message_id):
        calls["n"] += 1
        if calls["n"] == 2:
            raise PublishError("blip")
        original(routing_key, body, message_id)

    publisher.publish = flaky
    with pytest.raises(PublishError):
        relay.run_once()
    assert len(publisher.published) == 1  # first one went out and was committed as published
    publisher.publish = original
    assert relay.run_once() == 2
    assert len({m for _, _, m in publisher.published}) == 3  # no duplicates


def test_relay_thread_publishes_after_kick(tenants, relay, publisher):
    import time

    relay.start()
    try:
        tenants.create_tenant("acme", "Acme")  # on_commit -> relay.kick()
        deadline = time.time() + 5
        while not publisher.published and time.time() < deadline:
            time.sleep(0.02)
        assert len(publisher.published) == 1
    finally:
        relay.stop()
