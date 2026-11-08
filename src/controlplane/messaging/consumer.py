"""Consumer for worker progress updates (at-least-once in, effectively-once out).

Per message the outcome is one of:
  ACK          processed, or a harmless duplicate / stale update
  DEAD_LETTER  poison: unparsable, schema-invalid, unknown task, or an unexpected bug. Goes to the
               DLQ so it can be inspected; it never blocks the queue and never kills the consumer
  REQUEUE      transient failure (DB unavailable) that outlived the in-process retries; the broker
               redelivers it, so nothing is lost
Connection loss anywhere restarts the loop with exponential backoff.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable
from enum import StrEnum
from typing import Any

import pika
from pika.exceptions import AMQPError
from pydantic import ValidationError
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session, sessionmaker

from controlplane.config import Settings
from controlplane.errors import UnknownTaskError
from controlplane.messaging.backoff import backoff_delay
from controlplane.messaging.messages import TaskUpdate
from controlplane.messaging.topology import declare_topology
from controlplane.services.updates import UpdateResult, apply_update

log = logging.getLogger(__name__)

TRANSIENT_DB_ERRORS = (OperationalError, InterfaceError, PoolTimeoutError)

ApplyFn = Callable[[sessionmaker[Session], TaskUpdate], UpdateResult]


class Disposition(StrEnum):
    ACK = "ack"
    DEAD_LETTER = "dead_letter"
    REQUEUE = "requeue"


class UpdateConsumer:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        apply_fn: ApplyFn = apply_update,
    ) -> None:
        self._sf = session_factory
        self._s = settings
        self._apply = apply_fn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- message handling (no broker needed; unit-testable) ---------------------------
    def process(self, body: bytes) -> Disposition:
        try:
            msg = TaskUpdate.model_validate_json(body)
        except ValidationError as exc:
            log.warning("dead-lettering invalid update: %s", exc.errors(include_input=False))
            return Disposition.DEAD_LETTER

        attempt = 0
        while True:
            try:
                result = self._apply(self._sf, msg)
                log.info(
                    "update %s for task %s: %s",
                    msg.update_id,
                    msg.task_id,
                    result.outcome,
                )
                return Disposition.ACK
            except UnknownTaskError:
                log.warning("dead-lettering update %s: unknown task %s", msg.update_id, msg.task_id)
                return Disposition.DEAD_LETTER
            except TRANSIENT_DB_ERRORS as exc:
                attempt += 1
                if attempt >= self._s.consumer_max_attempts:
                    log.error("update %s still failing after %d attempts", msg.update_id, attempt)
                    return Disposition.REQUEUE
                delay = backoff_delay(attempt, self._s.backoff_base_s, self._s.backoff_max_s)
                log.warning("transient error (%r); retry %d in %.2fs", exc, attempt, delay)
                if self._stop.wait(delay):
                    return Disposition.REQUEUE
            except Exception:
                log.exception("dead-lettering update %s after unexpected error", msg.update_id)
                return Disposition.DEAD_LETTER

    def _settle(self, channel: Any, delivery_tag: int, disposition: Disposition) -> None:
        if disposition == Disposition.ACK:
            channel.basic_ack(delivery_tag)
        elif disposition == Disposition.DEAD_LETTER:
            channel.basic_nack(delivery_tag, requeue=False)
        else:
            self._stop.wait(min(self._s.backoff_max_s, 5.0))  # avoid a hot redelivery loop
            channel.basic_nack(delivery_tag, requeue=True)

    # ---- broker loop -------------------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="update-consumer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=15)

    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                self._consume()
                attempt = 0
            except (AMQPError, OSError) as exc:
                attempt += 1
                delay = backoff_delay(attempt, self._s.backoff_base_s, self._s.backoff_max_s)
                log.warning("broker connection lost (%r); reconnecting in %.1fs", exc, delay)
                self._stop.wait(delay)
            except Exception:
                attempt += 1
                delay = backoff_delay(attempt, self._s.backoff_base_s, self._s.backoff_max_s)
                log.exception("consumer crashed; restarting in %.1fs", delay)
                self._stop.wait(delay)

    def _consume(self) -> None:
        b = self._s.broker
        conn = pika.BlockingConnection(pika.URLParameters(b.amqp_url))
        try:
            channel = conn.channel()
            declare_topology(channel, b)
            channel.basic_qos(prefetch_count=self._s.consumer_prefetch)
            log.info("consuming task updates from %s", b.updates_queue)
            for method, _props, body in channel.consume(b.updates_queue, inactivity_timeout=1.0):
                if self._stop.is_set():
                    break
                if method is None:
                    continue
                self._settle(channel, method.delivery_tag, self.process(body))
            with contextlib.suppress(AMQPError, OSError):
                channel.cancel()
        finally:
            with contextlib.suppress(AMQPError, OSError):
                if conn.is_open:
                    conn.close()
