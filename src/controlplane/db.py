"""Engine / session helpers and schema bootstrap."""

from __future__ import annotations

import logging
import time

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from controlplane.models import Base

log = logging.getLogger(__name__)

_SCHEMA_LOCK_KEY = 727274  # arbitrary constant for pg_advisory_xact_lock


def normalize_url(url: str) -> str:
    """Accept plain postgres:// URLs but always use the psycopg v3 driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def make_engine(url: str) -> Engine:
    return create_engine(normalize_url(url), pool_pre_ping=True, pool_size=10, max_overflow=10)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: rows stay readable after the transaction ends.
    return sessionmaker(engine, expire_on_commit=False)


def init_schema(engine: Engine, attempts: int = 30, delay_s: float = 1.0) -> None:
    """Create tables if missing. Waits for the database to accept connections, and takes an
    advisory lock so concurrent replicas starting together do not race on DDL."""
    for attempt in range(1, attempts + 1):
        try:
            with engine.begin() as conn:
                conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SCHEMA_LOCK_KEY})
                Base.metadata.create_all(conn)
            return
        except OperationalError:
            if attempt == attempts:
                raise
            log.warning("database not ready (attempt %d/%d), retrying", attempt, attempts)
            time.sleep(delay_s)
