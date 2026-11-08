"""Time and id helpers. Timestamps are truncated to milliseconds so that what we store is
exactly what we serialize."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def utcnow() -> datetime:
    now = datetime.now(UTC)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def new_id() -> str:
    return str(uuid.uuid4())


def fmt_ts(dt: datetime) -> str:
    """ISO 8601, millisecond precision, `Z` suffix."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
