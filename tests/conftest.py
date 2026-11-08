from __future__ import annotations

import os
import threading
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from controlplane.api.app import create_app
from controlplane.config import BrokerSettings, Settings
from controlplane.db import init_schema, make_engine, make_session_factory
from controlplane.messaging.messages import TaskUpdate
from controlplane.messaging.publisher import PublishError
from controlplane.messaging.relay import OutboxRelay
from controlplane.services.tenants import TenantService
from controlplane.services.updates import apply_update


class FakePublisher:
    """In-memory stand-in for the broker. Can be told to fail the next N publishes."""

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, str]] = []
        self.fail_next = 0
        self._lock = threading.Lock()

    def publish(self, routing_key: str, body: bytes, message_id: str) -> None:
        with self._lock:
            if self.fail_next > 0:
                self.fail_next -= 1
                raise PublishError("simulated broker outage")
            self.published.append((routing_key, body, message_id))

    def close(self) -> None:
        pass


@pytest.fixture(scope="session")
def engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set; run the suite with `make test`")
    eng = make_engine(url)
    init_schema(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE processed_updates, tasks, tenants"))
    return make_session_factory(engine)


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        database_url="unused",
        broker=BrokerSettings(amqp_url="amqp://unused"),
        relay_batch_size=10,
        backoff_base_s=0.01,
        backoff_max_s=0.05,
        consumer_max_attempts=3,
    )


@pytest.fixture()
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture()
def relay(session_factory, publisher, settings) -> OutboxRelay:
    return OutboxRelay(session_factory, publisher, settings)


@pytest.fixture()
def tenants(session_factory, relay) -> TenantService:
    return TenantService(session_factory, on_commit=relay.kick)


@pytest.fixture()
def client(engine, session_factory, publisher, settings):
    app = create_app(settings, engine=engine, publisher=publisher, run_background=False)
    with TestClient(app) as c:
        yield c


# ---- helpers -------------------------------------------------------------------------------
def send(session_factory, task_id: str, status: str, update_id: str | None = None, error=None):
    """Apply a worker update the way the consumer would."""
    msg = TaskUpdate(
        update_id=update_id or f"{task_id}:{status}", task_id=task_id, status=status, error=error
    )
    return apply_update(session_factory, msg)


def drive(session_factory, task_id: str, outcome: str = "done") -> None:
    """Walk a task accepted -> in_progress -> outcome."""
    send(session_factory, task_id, "in_progress")
    send(session_factory, task_id, outcome)
