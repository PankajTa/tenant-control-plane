"""Wiring: builds the services and background workers once per app instance."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from controlplane.config import Settings
from controlplane.db import make_engine, make_session_factory
from controlplane.messaging.consumer import UpdateConsumer
from controlplane.messaging.publisher import EventPublisher, RabbitPublisher
from controlplane.messaging.relay import OutboxRelay
from controlplane.services.tasks import TaskService
from controlplane.services.tenants import TenantService


@dataclass
class AppContext:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    relay: OutboxRelay
    consumer: UpdateConsumer
    tenants: TenantService
    tasks: TaskService
    run_background: bool


def build_context(
    settings: Settings,
    *,
    engine: Engine | None = None,
    publisher: EventPublisher | None = None,
    run_background: bool = True,
) -> AppContext:
    engine = engine or make_engine(settings.database_url)
    sf = make_session_factory(engine)
    relay = OutboxRelay(sf, publisher or RabbitPublisher(settings.broker), settings)
    return AppContext(
        settings=settings,
        engine=engine,
        session_factory=sf,
        relay=relay,
        consumer=UpdateConsumer(sf, settings),
        tenants=TenantService(sf, on_commit=relay.kick),
        tasks=TaskService(sf),
        run_background=run_background,
    )
