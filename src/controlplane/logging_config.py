"""Asynchronous JSON logging.

Application threads only enqueue log records (non-blocking); a dedicated QueueListener thread
formats and writes them to stdout. A slow or blocked stdout therefore never stalls request
handling, the outbox relay, or the consumer. One JSON object per line is what log shippers
(CloudWatch agent, Fluent Bit, Loki...) expect.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import queue
import sys
import time
from typing import IO

_STD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        payload.update({k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS})
        return json.dumps(payload, default=str)


def configure_logging(
    level: str = "INFO", stream: IO[str] | None = None
) -> logging.handlers.QueueListener:
    """Install async logging on the root logger. Returns the listener; call .stop() to flush."""
    out = logging.StreamHandler(stream or sys.stdout)
    formatter = JsonFormatter()
    formatter.converter = time.gmtime  # timestamps in UTC to match the `Z`
    out.setFormatter(formatter)

    q: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    listener = logging.handlers.QueueListener(q, out, respect_handler_level=True)

    root = logging.getLogger()
    root.handlers[:] = [_NoFormatQueueHandler(q)]
    root.setLevel(level.upper())
    listener.start()
    return listener


class _NoFormatQueueHandler(logging.handlers.QueueHandler):
    """Enqueue the record untouched, so the listener's JsonFormatter sees exc_info and extras."""

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return record
