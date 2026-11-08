"""Runtime configuration. Everything comes from environment variables; nothing secret is
ever stored in the repository."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"missing required environment variable {name}")
    return value


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class BrokerSettings:
    """Broker addressing. Shared by the control plane and the worker simulator."""

    amqp_url: str
    exchange: str = "controlplane"
    tasks_queue: str = "worker.tasks"
    updates_queue: str = "controlplane.task-updates"
    updates_dlq: str = "controlplane.task-updates.dlq"

    @property
    def dead_letter_exchange(self) -> str:
        return f"{self.exchange}.dlx"

    @classmethod
    def from_env(cls) -> BrokerSettings:
        return cls(amqp_url=_required("AMQP_URL"))


@dataclass(frozen=True)
class Settings:
    database_url: str
    broker: BrokerSettings
    relay_poll_interval_s: float = 2.0
    relay_batch_size: int = 50
    consumer_prefetch: int = 10
    consumer_max_attempts: int = 5
    backoff_base_s: float = 0.5
    backoff_max_s: float = 30.0
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=_required("DATABASE_URL"),
            broker=BrokerSettings.from_env(),
            relay_poll_interval_s=_float("RELAY_POLL_INTERVAL_S", 2.0),
            relay_batch_size=_int("RELAY_BATCH_SIZE", 50),
            consumer_prefetch=_int("CONSUMER_PREFETCH", 10),
            consumer_max_attempts=_int("CONSUMER_MAX_ATTEMPTS", 5),
            backoff_base_s=_float("BACKOFF_BASE_S", 0.5),
            backoff_max_s=_float("BACKOFF_MAX_S", 30.0),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
