"""REST API.

  POST   /v1/tenants                 201 + Location   create tenant, creates `deploy` task
  GET    /v1/tenants                 200              list (filter: status; page: limit/offset)
  GET    /v1/tenants/{id}            200
  PATCH  /v1/tenants/{id}            200              body carries `version` (optimistic lock)
  DELETE /v1/tenants/{id}            202              tenant -> destroying, creates `destroy` task
  GET    /v1/tenants/{id}/tasks      200              tasks of one tenant
  GET    /v1/tasks                   200              filters: tenant_id, status, type
  GET    /v1/tasks/{id}              200
  GET    /healthz, /readyz
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import text

from controlplane.api.context import AppContext
from controlplane.schemas import (
    TaskOut,
    TaskPage,
    TenantCreate,
    TenantMutationOut,
    TenantOut,
    TenantPage,
    TenantPatch,
)
from controlplane.services.tasks import TaskService
from controlplane.services.tenants import TenantService
from controlplane.state import TaskStatus, TaskType, TenantStatus


def _ctx(request: Request) -> AppContext:
    return request.app.state.ctx  # type: ignore[no-any-return]


def get_tenant_service(request: Request) -> TenantService:
    return _ctx(request).tenants


def get_task_service(request: Request) -> TaskService:
    return _ctx(request).tasks


TenantSvc = Annotated[TenantService, Depends(get_tenant_service)]
TaskSvc = Annotated[TaskService, Depends(get_task_service)]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]

router = APIRouter(prefix="/v1")
health = APIRouter()


# ---- tenants -----------------------------------------------------------------------------
@router.post("/tenants", status_code=201, response_model=TenantMutationOut, tags=["tenants"])
def create_tenant(body: TenantCreate, response: Response, svc: TenantSvc) -> TenantMutationOut:
    tenant, task = svc.create_tenant(body.slug, body.name)
    response.headers["Location"] = f"/v1/tenants/{tenant.id}"
    return TenantMutationOut.build(tenant, task)


@router.get("/tenants", response_model=TenantPage, tags=["tenants"])
def list_tenants(
    svc: TenantSvc,
    status: TenantStatus | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> TenantPage:
    rows, total = svc.list_tenants(status=status, limit=limit, offset=offset)
    return TenantPage(
        items=[TenantOut.from_model(t) for t in rows], total=total, limit=limit, offset=offset
    )


@router.get("/tenants/{tenant_id}", response_model=TenantOut, tags=["tenants"])
def get_tenant(tenant_id: str, svc: TenantSvc) -> TenantOut:
    return TenantOut.from_model(svc.get_tenant(tenant_id))


@router.patch("/tenants/{tenant_id}", response_model=TenantMutationOut, tags=["tenants"])
def patch_tenant(tenant_id: str, body: TenantPatch, svc: TenantSvc) -> TenantMutationOut:
    tenant, task = svc.update_tenant(tenant_id, body.version, body.name)
    return TenantMutationOut.build(tenant, task)


@router.delete("/tenants/{tenant_id}", status_code=202, response_model=TenantMutationOut, tags=["tenants"])
def delete_tenant(tenant_id: str, svc: TenantSvc) -> TenantMutationOut:
    tenant, task = svc.delete_tenant(tenant_id)
    return TenantMutationOut.build(tenant, task)


@router.get("/tenants/{tenant_id}/tasks", response_model=TaskPage, tags=["tasks"])
def list_tenant_tasks(
    tenant_id: str,
    tenants: TenantSvc,
    tasks: TaskSvc,
    status: TaskStatus | None = None,
    type: TaskType | None = None,  # noqa: A002 - public query parameter name
    limit: Limit = 50,
    offset: Offset = 0,
) -> TaskPage:
    tenants.get_tenant(tenant_id)  # 404 tenant_not_found for unknown tenants
    rows, total = tasks.list_tasks(
        tenant_id=tenant_id, status=status, task_type=type, limit=limit, offset=offset
    )
    return TaskPage(
        items=[TaskOut.from_model(t) for t in rows], total=total, limit=limit, offset=offset
    )


# ---- tasks (read-only) -------------------------------------------------------------------
@router.get("/tasks", response_model=TaskPage, tags=["tasks"])
def list_tasks(
    tasks: TaskSvc,
    tenant_id: str | None = None,
    status: TaskStatus | None = None,
    type: TaskType | None = None,  # noqa: A002
    limit: Limit = 50,
    offset: Offset = 0,
) -> TaskPage:
    rows, total = tasks.list_tasks(
        tenant_id=tenant_id, status=status, task_type=type, limit=limit, offset=offset
    )
    return TaskPage(
        items=[TaskOut.from_model(t) for t in rows], total=total, limit=limit, offset=offset
    )


@router.get("/tasks/{task_id}", response_model=TaskOut, tags=["tasks"])
def get_task(task_id: str, tasks: TaskSvc) -> TaskOut:
    return TaskOut.from_model(tasks.get_task(task_id))


# ---- health ------------------------------------------------------------------------------
@health.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@health.get("/readyz", tags=["ops"])
def readyz(request: Request, response: Response) -> dict[str, str]:
    try:
        with _ctx(request).engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        response.status_code = 503
        return {"status": "database_unavailable"}
    return {"status": "ready"}
