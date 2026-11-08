"""Pure state-machine rules. No I/O here, so every transition is trivially unit-testable."""

from __future__ import annotations

from enum import StrEnum


class TenantStatus(StrEnum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    UPDATING = "updating"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"
    FAILED = "failed"


class TaskStatus(StrEnum):
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class TaskType(StrEnum):
    DEPLOY = "deploy"
    UPDATE = "update"
    DESTROY = "destroy"


TERMINAL_TASK_STATUSES = frozenset({TaskStatus.DONE, TaskStatus.FAILED})
OPEN_TASK_STATUSES = frozenset({TaskStatus.ACCEPTED, TaskStatus.IN_PROGRESS})

UPDATABLE_FROM = frozenset({TenantStatus.ACTIVE})
DELETABLE_FROM = frozenset({TenantStatus.ACTIVE, TenantStatus.FAILED})

# The tenant status each task type runs the tenant through while it is open.
_TENANT_STATUS_DURING = {
    TaskType.DEPLOY: TenantStatus.PROVISIONING,
    TaskType.UPDATE: TenantStatus.UPDATING,
    TaskType.DESTROY: TenantStatus.DESTROYING,
}
_TENANT_STATUS_ON_DONE = {
    TaskType.DEPLOY: TenantStatus.ACTIVE,
    TaskType.UPDATE: TenantStatus.ACTIVE,
    TaskType.DESTROY: TenantStatus.DESTROYED,
}


def next_task_status(current: TaskStatus, incoming: TaskStatus) -> TaskStatus | None:
    """Decide what a worker update does to a task.

    Returns the status to move to, or None when the update is stale / a no-op and must be
    ignored (never an error: with at-least-once delivery, late messages are normal).

    Legal path: accepted -> in_progress -> done | failed.
    Tolerance: a terminal update that overtakes `in_progress` (accepted -> done|failed) is
    applied; the late `in_progress` is then dropped as stale. Dropping the terminal update
    instead would leave the task stuck forever, because the worker never re-sends it.
    """
    if current in TERMINAL_TASK_STATUSES:
        return None
    if incoming == TaskStatus.ACCEPTED:
        return None
    if current == TaskStatus.IN_PROGRESS and incoming == TaskStatus.IN_PROGRESS:
        return None
    return incoming


def tenant_status_after(
    task_type: TaskType, outcome: TaskStatus, tenant_status: TenantStatus
) -> TenantStatus | None:
    """Tenant status after a *terminal* task outcome, or None if the tenant is not in the
    state this task type expects (then the tenant is left alone)."""
    if outcome not in TERMINAL_TASK_STATUSES:
        return None
    if tenant_status != _TENANT_STATUS_DURING[task_type]:
        return None
    if outcome == TaskStatus.DONE:
        return _TENANT_STATUS_ON_DONE[task_type]
    return TenantStatus.FAILED
