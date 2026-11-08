"""Broker publisher. Publisher confirms + `mandatory` mean publish() only returns once the broker
has accepted AND routed the message; any doubt raises PublishError (the outbox then retries)."""

from __future__ import annotations

import contextlib
import logging
from typing import Protocol

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import AMQPError

from controlplane.config import BrokerSettings
from controlplane.messaging.topology import declare_topology

log = logging.getLogger(__name__)


class PublishError(Exception):
    pass


class EventPublisher(Protocol):
    def publish(self, routing_key: str, body: bytes, message_id: str) -> None: ...

    def close(self) -> None: ...


class RabbitPublisher:
    """Not thread-safe by design: owned by the single relay thread."""

    def __init__(self, broker: BrokerSettings) -> None:
        self._broker = broker
        self._conn: pika.BlockingConnection | None = None
        self._channel: BlockingChannel | None = None

    def _ensure(self) -> BlockingChannel:
        if (
            self._conn is not None
            and self._conn.is_open
            and self._channel is not None
            and self._channel.is_open
        ):
            return self._channel
        self.close()
        conn = pika.BlockingConnection(pika.URLParameters(self._broker.amqp_url))
        channel = conn.channel()
        channel.confirm_delivery()
        declare_topology(channel, self._broker)
        self._conn, self._channel = conn, channel
        return channel

    def publish(self, routing_key: str, body: bytes, message_id: str) -> None:
        last: Exception | None = None
        for _ in range(2):  # one transparent reconnect for stale idle connections
            try:
                channel = self._ensure()
                channel.basic_publish(
                    exchange=self._broker.exchange,
                    routing_key=routing_key,
                    body=body,
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # persistent
                        content_type="application/json",
                        message_id=message_id,
                    ),
                    mandatory=True,
                )
                return
            except (AMQPError, OSError) as exc:
                last = exc
                self.close()
        raise PublishError(f"publish failed: {last!r}") from last

    def close(self) -> None:
        conn, self._conn, self._channel = self._conn, None, None
        with contextlib.suppress(AMQPError, OSError):
            if conn is not None and conn.is_open:
                conn.close()
