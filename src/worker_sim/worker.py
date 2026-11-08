"""Worker simulator: consumes task events, "provisions", publishes progress updates.

Every update gets a *deterministic* idempotency key, `<task_id>:<status>`, so if the worker
crashes and the broker redelivers the task, the re-sent updates dedupe at the control plane.
"""

from __future__ import annotations

import contextlib
import logging
import random
import threading
from collections import OrderedDict
from dataclasses import dataclass

import pika
from pika.exceptions import AMQPError
from pydantic import ValidationError

from controlplane.clock import fmt_ts, utcnow
from controlplane.config import BrokerSettings
from controlplane.messaging.backoff import backoff_delay
from controlplane.messaging.messages import TaskEvent, TaskUpdate
from controlplane.messaging.topology import ROUTING_TASK_UPDATE, declare_topology
from worker_sim.config import WorkerConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Step:
    delay_s: float  # wait this long (simulated work) BEFORE publishing
    update: TaskUpdate


class Worker:
    def __init__(self, cfg: WorkerConfig, broker: BrokerSettings) -> None:
        self._cfg = cfg
        self._broker = broker
        self._rng = random.Random(cfg.seed)  # nosec B311 - simulation, not security
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._stop = threading.Event()

    # ---- planning (pure; unit-tested) ---------------------------------------------------
    def plan(self, event: TaskEvent) -> list[Step]:
        cfg, rng = self._cfg, self._rng
        work_s = rng.uniform(cfg.min_delay_ms, cfg.max_delay_ms) / 1000
        failed = rng.random() < cfg.fail_rate
        terminal_status = "failed" if failed else "done"

        def update(status: str, error: str | None = None) -> TaskUpdate:
            return TaskUpdate(
                update_id=f"{event.id}:{status}",
                task_id=event.id,
                status=status,  # type: ignore[arg-type]
                error=error,
                occurred_at=fmt_ts(utcnow()),
            )

        started = update("in_progress")
        finished = update(
            terminal_status, "simulated provisioning failure" if failed else None
        )
        if rng.random() < cfg.out_of_order_rate:
            ordered = [Step(work_s, finished), Step(0.0, started)]
        else:
            ordered = [Step(0.0, started), Step(work_s, finished)]

        steps: list[Step] = []
        for step in ordered:
            steps.append(step)
            if rng.random() < cfg.duplicate_rate:
                steps.append(Step(0.0, step.update))
        return steps

    # ---- I/O ----------------------------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                self._session()
                attempt = 0
            except (AMQPError, OSError) as exc:
                attempt += 1
                delay = backoff_delay(attempt, 0.5, 15.0)
                log.warning("broker connection problem (%r); retrying in %.1fs", exc, delay)
                self._stop.wait(delay)

    def _session(self) -> None:
        b = self._broker
        conn = pika.BlockingConnection(pika.URLParameters(b.amqp_url))
        try:
            ch = conn.channel()
            declare_topology(ch, b)
            ch.confirm_delivery()
            ch.basic_qos(prefetch_count=1)
            log.info("worker ready: consuming %s", b.tasks_queue)
            for method, _props, body in ch.consume(b.tasks_queue, inactivity_timeout=1.0):
                if self._stop.is_set():
                    break
                if method is None:
                    continue
                try:
                    event = TaskEvent.model_validate_json(body)
                except ValidationError:
                    log.warning("discarding malformed task event")
                    ch.basic_nack(method.delivery_tag, requeue=False)
                    continue
                if event.id in self._seen:
                    log.info("duplicate task event %s ignored", event.id)
                    ch.basic_ack(method.delivery_tag)
                    continue
                for step in self.plan(event):
                    if step.delay_s > 0:
                        conn.sleep(step.delay_s)  # keeps heartbeats flowing while "working"
                    ch.basic_publish(
                        b.exchange,
                        ROUTING_TASK_UPDATE,
                        step.update.model_dump_json().encode(),
                        pika.BasicProperties(
                            delivery_mode=2,
                            content_type="application/json",
                            message_id=step.update.update_id,
                        ),
                        mandatory=True,
                    )
                    log.info("task %s -> %s", event.id, step.update.status)
                ch.basic_ack(method.delivery_tag)
                self._seen[event.id] = None
                while len(self._seen) > 10_000:
                    self._seen.popitem(last=False)
            with contextlib.suppress(AMQPError, OSError):
                ch.cancel()
        finally:
            with contextlib.suppress(AMQPError, OSError):
                if conn.is_open:
                    conn.close()
