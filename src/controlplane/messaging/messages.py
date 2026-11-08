"""Wire format (JSON). Both directions are versionless on purpose; unknown fields are ignored so
either side can add fields without breaking the other.

Outbound  (control plane -> worker)  routing key `task.created`, queue `worker.tasks`
    The task itself: {id, type, tenant_id, status, created_at, updated_at}.
    `id` is the task id and doubles as the event id.

Inbound   (worker -> control plane)  routing key `task.update`, queue `controlplane.task-updates`
    {update_id, task_id, status: in_progress|done|failed, error?, occurred_at?}
    `update_id` is the idempotency key; `task_id` references the task being updated.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from controlplane.clock import fmt_ts
from controlplane.models import Task
from controlplane.state import TaskStatus, TaskType


class TaskEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    type: TaskType
    tenant_id: str
    status: TaskStatus
    created_at: str
    updated_at: str

    @classmethod
    def from_task(cls, t: Task) -> TaskEvent:
        return cls(
            id=t.id,
            type=TaskType(t.type),
            tenant_id=t.tenant_id,
            status=TaskStatus(t.status),
            created_at=fmt_ts(t.created_at),
            updated_at=fmt_ts(t.updated_at),
        )


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    update_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=36)
    status: Literal["in_progress", "done", "failed"]
    error: str | None = None
    occurred_at: str | None = None
