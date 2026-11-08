"""Task read path (tasks are read-only over HTTP)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from controlplane.errors import TaskNotFound
from controlplane.models import Task
from controlplane.state import TaskStatus, TaskType


class TaskService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def get_task(self, task_id: str) -> Task:
        with self._sf() as s:
            task = s.get(Task, task_id)
            if task is None:
                raise TaskNotFound(f"task {task_id} not found")
            return task

    def list_tasks(
        self,
        *,
        tenant_id: str | None,
        status: TaskStatus | None,
        task_type: TaskType | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Task], int]:
        with self._sf() as s:
            stmt = select(Task)
            count = select(func.count()).select_from(Task)
            for column, value in (
                (Task.tenant_id, tenant_id),
                (Task.status, status.value if status else None),
                (Task.type, task_type.value if task_type else None),
            ):
                if value is not None:
                    stmt = stmt.where(column == value)
                    count = count.where(column == value)
            total = s.scalar(count) or 0
            rows = s.scalars(
                stmt.order_by(Task.created_at.desc(), Task.id.desc()).limit(limit).offset(offset)
            ).all()
            return list(rows), total
