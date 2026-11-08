"""End-to-end through a REAL RabbitMQ: API -> outbox relay -> broker -> worker -> broker ->
consumer -> DB. Needs TEST_AMQP_URL (set by docker-compose.test.yml)."""

from __future__ import annotations

import os
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from controlplane.api.app import create_app
from controlplane.config import BrokerSettings, Settings
from worker_sim.config import WorkerConfig
from worker_sim.worker import Worker

pytestmark = pytest.mark.e2e

AMQP = os.environ.get("TEST_AMQP_URL")


def wait_for(fn, timeout=30.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")


@pytest.fixture()
def stack(engine, session_factory):
    """Boot the app (relay + consumer threads) and a worker, on a private broker namespace."""
    if not AMQP:
        pytest.skip("TEST_AMQP_URL not set")
    ns = uuid.uuid4().hex[:8]
    broker = BrokerSettings(
        amqp_url=AMQP,
        exchange=f"cp-{ns}",
        tasks_queue=f"cp-{ns}.tasks",
        updates_queue=f"cp-{ns}.updates",
        updates_dlq=f"cp-{ns}.updates.dlq",
    )
    settings = Settings(
        database_url="unused", broker=broker, relay_poll_interval_s=0.2, backoff_base_s=0.05
    )
    started: list[Worker] = []

    def start_worker(fail_rate: float = 0.0) -> None:
        w = Worker(WorkerConfig(fail_rate=fail_rate, min_delay_ms=50, max_delay_ms=100), broker)
        threading.Thread(target=w.run, daemon=True).start()
        started.append(w)

    app = create_app(settings, engine=engine, run_background=True)
    with TestClient(app) as client:
        yield client, start_worker
    for w in started:
        w.stop()


def test_full_lifecycle_deploy_update_destroy(stack):
    client, start_worker = stack
    start_worker()

    t = client.post("/v1/tenants", json={"slug": "e2e-ok", "name": "E2E"}).json()
    wait_for(lambda: client.get(f"/v1/tenants/{t['id']}").json()["status"] == "active")
    task = client.get(f"/v1/tasks/{t['task_id']}").json()
    assert task["status"] == "done"

    t = client.get(f"/v1/tenants/{t['id']}").json()
    client.patch(f"/v1/tenants/{t['id']}", json={"version": t["version"], "name": "Renamed"})
    wait_for(lambda: client.get(f"/v1/tenants/{t['id']}").json()["status"] == "active")

    client.delete(f"/v1/tenants/{t['id']}")
    wait_for(lambda: client.get(f"/v1/tenants/{t['id']}").json()["status"] == "destroyed")
    tasks = client.get(f"/v1/tenants/{t['id']}/tasks").json()["items"]
    assert sorted(x["type"] for x in tasks) == ["deploy", "destroy", "update"]
    assert all(x["status"] == "done" for x in tasks)


def test_failing_worker_marks_tenant_failed_and_it_can_be_destroyed(stack):
    client, start_worker = stack
    start_worker(fail_rate=1.0)

    t = client.post("/v1/tenants", json={"slug": "e2e-fail", "name": "E2E"}).json()
    wait_for(lambda: client.get(f"/v1/tenants/{t['id']}").json()["status"] == "failed")
    assert client.get(f"/v1/tasks/{t['task_id']}").json()["status"] == "failed"

    assert client.delete(f"/v1/tenants/{t['id']}").status_code == 202


def test_out_of_order_and_duplicate_deliveries_converge(stack, engine):
    client, _ = stack
    broker = client.app.state.ctx.settings.broker
    w = Worker(
        WorkerConfig(
            min_delay_ms=10, max_delay_ms=20, duplicate_rate=1.0, out_of_order_rate=1.0
        ),
        broker,
    )
    threading.Thread(target=w.run, daemon=True).start()
    try:
        t = client.post("/v1/tenants", json={"slug": "e2e-chaos", "name": "E2E"}).json()
        wait_for(lambda: client.get(f"/v1/tenants/{t['id']}").json()["status"] == "active")
        time.sleep(1)  # let the late/duplicate messages arrive; they must change nothing
        final = client.get(f"/v1/tenants/{t['id']}").json()
        assert (final["status"], final["version"]) == ("active", 2)
        assert client.get(f"/v1/tasks/{t['task_id']}").json()["status"] == "done"
    finally:
        w.stop()
