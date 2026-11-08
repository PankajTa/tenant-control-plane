"""RabbitMQ topology, declared idempotently by every process that touches the broker."""

from __future__ import annotations

from typing import Any

from controlplane.config import BrokerSettings

ROUTING_TASK_CREATED = "task.created"
ROUTING_TASK_UPDATE = "task.update"


def declare_topology(channel: Any, b: BrokerSettings) -> None:
    channel.exchange_declare(exchange=b.exchange, exchange_type="direct", durable=True)
    channel.exchange_declare(exchange=b.dead_letter_exchange, exchange_type="direct", durable=True)

    # control plane -> worker
    channel.queue_declare(queue=b.tasks_queue, durable=True)
    channel.queue_bind(queue=b.tasks_queue, exchange=b.exchange, routing_key=ROUTING_TASK_CREATED)

    # worker -> control plane; rejected (poison) messages are dead-lettered, not lost or looped
    channel.queue_declare(queue=b.updates_dlq, durable=True)
    channel.queue_bind(
        queue=b.updates_dlq, exchange=b.dead_letter_exchange, routing_key=ROUTING_TASK_UPDATE
    )
    channel.queue_declare(
        queue=b.updates_queue,
        durable=True,
        arguments={
            "x-dead-letter-exchange": b.dead_letter_exchange,
            "x-dead-letter-routing-key": ROUTING_TASK_UPDATE,
        },
    )
    channel.queue_bind(
        queue=b.updates_queue, exchange=b.exchange, routing_key=ROUTING_TASK_UPDATE
    )
