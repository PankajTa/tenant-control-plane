"""Inbound worker updates: idempotent, order-tolerant, applied atomically.

One transaction per update:
  1. lock the task row (FOR UPDATE) -> serialises concurrent deliveries for the same task
  2. insert the update_id into the idempotency ledger (ON CONFLICT DO NOTHING)
  3. apply the task transition (if not stale) and, on a terminal outcome, the tenant transition
The ledger insert and the state change commit together, so a crash can never record an update
as processed without applying it (or vice versa).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from controlplane.clock import utcnow
from controlplane.errors import UnknownTaskError
from controlplane.messaging.messages import TaskUpdate
from controlplane.models import ProcessedUpdate, Task, Tenant
from controlplane.state import (
    TERMINAL_TASK_STATUSES,
    TaskStatus,
    TaskType,
    TenantStatus,
    next_task_status,
    tenant_status_after,
)

log = logging.getLogger(__name__)


class Outcome(StrEnum):
    APPLIED = "applied"
    STALE = "stale"  # valid message, but it would not move the task forward
    DUPLICATE = "duplicate"  # update_id already processed


@dataclass(frozen=True)
class UpdateResult:
    outcome: Outcome
    task_status: str
    tenant_status: str | None = None


def apply_update(session_factory: sessionmaker[Session], msg: TaskUpdate) -> UpdateResult:
    now = utcnow()
    with session_factory.begin() as s:
        task = s.execute(select(Task).where(Task.id == msg.task_id).with_for_update()).scalar()
        if task is None:
            raise UnknownTaskError(msg.task_id)

        new_status = next_task_status(TaskStatus(task.status), TaskStatus(msg.status))
        outcome = Outcome.STALE if new_status is None else Outcome.APPLIED

        inserted = s.execute(
            pg_insert(ProcessedUpdate)
            .values(
                update_id=msg.update_id,
                task_id=msg.task_id,
                outcome=outcome.value,
                received_at=now,
            )
            .on_conflict_do_nothing(index_elements=["update_id"])
        )
        if inserted.rowcount == 0:  # type: ignore[attr-defined]
            log.info("duplicate update ignored", extra={"update_id": msg.update_id})
            return UpdateResult(Outcome.DUPLICATE, task.status)

        if new_status is None:
            log.info(
                "stale update ignored: task=%s is %s, got %s",
                task.id,
                task.status,
                msg.status,
            )
            return UpdateResult(Outcome.STALE, task.status)

        task.status = new_status.value
        task.updated_at = now
        if new_status == TaskStatus.FAILED:
            task.error = msg.error or "task failed"

        tenant_status: str | None = None
        if new_status in TERMINAL_TASK_STATUSES:
            # Lock order is always task -> tenant. The HTTP path only locks the tenant row and
            # inserts a *new* task, so there is no cycle.
            tenant = s.execute(
                select(Tenant).where(Tenant.id == task.tenant_id).with_for_update()
            ).scalar_one()
            target = tenant_status_after(
                TaskType(task.type), new_status, TenantStatus(tenant.status)
            )
            if target is not None:
                tenant.status = target.value
                tenant.version += 1
                tenant.updated_at = now
            else:
                log.warning(
                    "tenant %s in status %s not moved by terminal %s %s",
                    tenant.id,
                    tenant.status,
                    task.type,
                    new_status,
                )
            tenant_status = tenant.status
        return UpdateResult(Outcome.APPLIED, task.status, tenant_status)
