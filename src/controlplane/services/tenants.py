"""Tenant write path.

Every mutation is ONE database transaction that changes the tenant and inserts its task.
Nothing is sent to the broker here: the task row is the outbox entry, and the relay publishes
it only after this transaction has committed. `on_commit` merely wakes the relay up.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from controlplane.clock import new_id, utcnow
from controlplane.errors import (
    TenantAlreadyExists,
    TenantNotFound,
    TenantUpdateNotAllowed,
    TenantVersionConflict,
)
from controlplane.models import Task, Tenant
from controlplane.state import (
    DELETABLE_FROM,
    UPDATABLE_FROM,
    TaskStatus,
    TaskType,
    TenantStatus,
)


def _new_task(tenant_id: str, task_type: TaskType, now: datetime) -> Task:
    return Task(
        id=new_id(),
        type=task_type.value,
        tenant_id=tenant_id,
        status=TaskStatus.ACCEPTED.value,
        error=None,
        created_at=now,
        updated_at=now,
        published_at=None,
    )


class TenantService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        on_commit: Callable[[], None] | None = None,
    ) -> None:
        self._sf = session_factory
        self._on_commit = on_commit or (lambda: None)

    # ---- reads -------------------------------------------------------------------------
    def get_tenant(self, tenant_id: str) -> Tenant:
        with self._sf() as s:
            tenant = s.get(Tenant, tenant_id)
            if tenant is None:
                raise TenantNotFound(f"tenant {tenant_id} not found")
            return tenant

    def list_tenants(
        self, *, status: TenantStatus | None, limit: int, offset: int
    ) -> tuple[list[Tenant], int]:
        with self._sf() as s:
            stmt = select(Tenant)
            count = select(func.count()).select_from(Tenant)
            if status is not None:
                stmt = stmt.where(Tenant.status == status.value)
                count = count.where(Tenant.status == status.value)
            total = s.scalar(count) or 0
            rows = s.scalars(
                stmt.order_by(Tenant.created_at.desc(), Tenant.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            return list(rows), total

    # ---- writes ------------------------------------------------------------------------
    def create_tenant(self, slug: str, name: str) -> tuple[Tenant, Task]:
        now = utcnow()
        tenant = Tenant(
            id=new_id(),
            slug=slug,
            name=name,
            status=TenantStatus.PROVISIONING.value,
            version=1,
            created_at=now,
            updated_at=now,
        )
        task = _new_task(tenant.id, TaskType.DEPLOY, now)
        try:
            with self._sf.begin() as s:
                s.add(tenant)
                s.flush()  # the UNIQUE(slug) check happens here; exactly one racer wins
                s.add(task)
        except IntegrityError:
            with self._sf() as s:
                taken = s.scalar(select(Tenant.id).where(Tenant.slug == slug))
            if taken is not None:
                raise TenantAlreadyExists(
                    f"a tenant with slug '{slug}' already exists", {"slug": slug}
                ) from None
            raise
        self._on_commit()
        return tenant, task

    def update_tenant(self, tenant_id: str, version: int, name: str | None) -> tuple[Tenant, Task]:
        """Optimistic locking in a single conditional UPDATE: the WHERE clause carries both the
        version and the status guard, so of N concurrent callers with the same version exactly
        one matches a row (the others re-evaluate the WHERE after the winner commits)."""
        now = utcnow()
        values: dict[str, Any] = {
            "status": TenantStatus.UPDATING.value,
            "version": Tenant.version + 1,
            "updated_at": now,
        }
        if name is not None:
            values["name"] = name
        with self._sf.begin() as s:
            result = s.execute(
                update(Tenant)
                .where(
                    Tenant.id == tenant_id,
                    Tenant.version == version,
                    Tenant.status.in_([x.value for x in UPDATABLE_FROM]),
                )
                .values(**values)
            )
            if result.rowcount == 0:  # type: ignore[attr-defined]
                self._raise_update_failure(s, tenant_id, version)
            task = _new_task(tenant_id, TaskType.UPDATE, now)
            s.add(task)
            tenant = s.get(Tenant, tenant_id, populate_existing=True)
        self._on_commit()
        if tenant is None:  # pragma: no cover - row was just updated in this transaction
            raise TenantNotFound(f"tenant {tenant_id} not found")
        return tenant, task

    def delete_tenant(self, tenant_id: str) -> tuple[Tenant, Task]:
        now = utcnow()
        with self._sf.begin() as s:
            result = s.execute(
                update(Tenant)
                .where(
                    Tenant.id == tenant_id,
                    Tenant.status.in_([x.value for x in DELETABLE_FROM]),
                )
                .values(
                    status=TenantStatus.DESTROYING.value,
                    version=Tenant.version + 1,
                    updated_at=now,
                )
            )
            if result.rowcount == 0:  # type: ignore[attr-defined]
                current = s.get(Tenant, tenant_id, populate_existing=True)
                if current is None:
                    raise TenantNotFound(f"tenant {tenant_id} not found")
                raise TenantUpdateNotAllowed(
                    f"tenant in status '{current.status}' cannot be deleted "
                    "(only 'active' or 'failed')",
                    {"status": current.status},
                )
            task = _new_task(tenant_id, TaskType.DESTROY, now)
            s.add(task)
            tenant = s.get(Tenant, tenant_id, populate_existing=True)
        self._on_commit()
        if tenant is None:  # pragma: no cover
            raise TenantNotFound(f"tenant {tenant_id} not found")
        return tenant, task

    @staticmethod
    def _raise_update_failure(s: Session, tenant_id: str, version: int) -> None:
        current = s.get(Tenant, tenant_id, populate_existing=True)
        if current is None:
            raise TenantNotFound(f"tenant {tenant_id} not found")
        if current.version != version:
            raise TenantVersionConflict(
                f"version {version} is stale; current version is {current.version}",
                {"expected_version": version, "current_version": current.version},
            )
        raise TenantUpdateNotAllowed(
            f"tenant in status '{current.status}' cannot be updated (only 'active')",
            {"status": current.status},
        )
