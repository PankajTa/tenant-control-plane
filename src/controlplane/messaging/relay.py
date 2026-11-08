"""Transactional-outbox relay.

The API commits tenant + task in one transaction. This relay then publishes every task that has
`published_at IS NULL` and marks it published. Consequences:
  * never published before commit, never published on rollback (it can only see committed rows);
  * a crash between "publish" and "mark published" re-publishes later => at-least-once, which the
    consumers are built for (workers dedupe on task id, the control plane on update_id);
  * FOR UPDATE SKIP LOCKED lets several replicas share the work without double-sending.
"""

from __future__ import annotations

import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from controlplane.clock import utcnow
from controlplane.config import Settings
from controlplane.messaging.backoff import backoff_delay
from controlplane.messaging.messages import TaskEvent
from controlplane.messaging.publisher import EventPublisher, PublishError
from controlplane.messaging.topology import ROUTING_TASK_CREATED
from controlplane.models import Task

log = logging.getLogger(__name__)


class OutboxRelay:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        publisher: EventPublisher,
        settings: Settings,
    ) -> None:
        self._sf = session_factory
        self._publisher = publisher
        self._s = settings
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- control ---------------------------------------------------------------------
    def kick(self) -> None:
        """Called after a commit: publish now instead of waiting for the next poll."""
        self._wake.set()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="outbox-relay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._publisher.close()

    # ---- work ------------------------------------------------------------------------
    def run_once(self) -> int:
        """Publish everything currently pending. Returns the number of events published."""
        total = 0
        while True:
            n = self._publish_batch()
            total += n
            if n < self._s.relay_batch_size:
                return total

    def _publish_batch(self) -> int:
        failure: PublishError | None = None
        published = 0
        with self._sf.begin() as s:
            tasks = s.scalars(
                select(Task)
                .where(Task.published_at.is_(None))
                .order_by(Task.created_at, Task.id)
                .limit(self._s.relay_batch_size)
                .with_for_update(skip_locked=True)
            ).all()
            for task in tasks:
                body = TaskEvent.from_task(task).model_dump_json().encode()
                try:
                    self._publisher.publish(ROUTING_TASK_CREATED, body, task.id)
                except PublishError as exc:
                    failure = exc
                    break  # keep what we already sent marked; retry the rest later
                task.published_at = utcnow()
                published += 1
        if failure is not None:
            raise failure
        return published

    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                self.run_once()
                attempt = 0
                wait = self._s.relay_poll_interval_s
            except Exception:
                attempt += 1
                wait = backoff_delay(attempt, self._s.backoff_base_s, self._s.backoff_max_s)
                log.exception("outbox relay failed (attempt %d); retrying in %.1fs", attempt, wait)
            self._wake.wait(wait)
            self._wake.clear()
