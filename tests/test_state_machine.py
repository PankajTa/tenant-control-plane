import pytest

from controlplane.state import (
    DELETABLE_FROM,
    UPDATABLE_FROM,
    TaskStatus,
    TaskType,
    TenantStatus,
    next_task_status,
    tenant_status_after,
)

A, P, D, F = (
    TaskStatus.ACCEPTED,
    TaskStatus.IN_PROGRESS,
    TaskStatus.DONE,
    TaskStatus.FAILED,
)


@pytest.mark.parametrize(
    ("current", "incoming", "expected"),
    [
        (A, P, P),
        (P, D, D),
        (P, F, F),
        (A, D, D),  # terminal overtook in_progress: applied, not dropped
        (A, F, F),
        (P, P, None),  # repeat
        (A, A, None),
        (P, A, None),  # regression
        (D, P, None),  # in_progress after done
        (D, F, None),  # terminal is final
        (F, D, None),
        (D, D, None),
        (F, P, None),
    ],
)
def test_task_transitions(current, incoming, expected):
    assert next_task_status(current, incoming) == expected


@pytest.mark.parametrize(
    ("task_type", "outcome", "tenant", "expected"),
    [
        (TaskType.DEPLOY, D, TenantStatus.PROVISIONING, TenantStatus.ACTIVE),
        (TaskType.UPDATE, D, TenantStatus.UPDATING, TenantStatus.ACTIVE),
        (TaskType.DESTROY, D, TenantStatus.DESTROYING, TenantStatus.DESTROYED),
        (TaskType.DEPLOY, F, TenantStatus.PROVISIONING, TenantStatus.FAILED),
        (TaskType.UPDATE, F, TenantStatus.UPDATING, TenantStatus.FAILED),
        (TaskType.DESTROY, F, TenantStatus.DESTROYING, TenantStatus.FAILED),
        # tenant not in the state this task type expects -> untouched
        (TaskType.DEPLOY, D, TenantStatus.ACTIVE, None),
        (TaskType.DESTROY, D, TenantStatus.FAILED, None),
        # non-terminal outcomes never move the tenant
        (TaskType.DEPLOY, P, TenantStatus.PROVISIONING, None),
    ],
)
def test_tenant_transitions(task_type, outcome, tenant, expected):
    assert tenant_status_after(task_type, outcome, tenant) == expected


def test_guards():
    assert {TenantStatus.ACTIVE} == UPDATABLE_FROM
    assert {TenantStatus.ACTIVE, TenantStatus.FAILED} == DELETABLE_FROM
