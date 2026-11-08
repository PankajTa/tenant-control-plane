"""HTTP request/response models."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from controlplane.clock import fmt_ts
from controlplane.models import Task, Tenant

SLUG_PATTERN = r"^[a-z][-a-z0-9]{1,26}[a-z0-9]$"

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=SLUG_PATTERN, description="k8s-namespace compatible, 3-28 chars")
    name: Name


class TenantPatch(BaseModel):
    """Partial update. `slug` is immutable, so only `name` can change. `version` is the
    optimistic-lock token the client last read."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    name: Name | None = None

    @model_validator(mode="after")
    def _needs_a_change(self) -> TenantPatch:
        if self.name is None:
            raise ValueError("at least one updatable field (name) is required")
        return self


class TenantOut(BaseModel):
    id: str
    slug: str
    name: str
    status: str
    version: int
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, t: Tenant) -> TenantOut:
        return cls(
            id=t.id,
            slug=t.slug,
            name=t.name,
            status=t.status,
            version=t.version,
            created_at=fmt_ts(t.created_at),
            updated_at=fmt_ts(t.updated_at),
        )


class TenantMutationOut(TenantOut):
    """Returned by mutating calls: the tenant plus the task the call created."""

    task_id: str

    @classmethod
    def build(cls, tenant: Tenant, task: Task) -> TenantMutationOut:
        return cls(**TenantOut.from_model(tenant).model_dump(), task_id=task.id)


class TaskOut(BaseModel):
    id: str
    type: str
    tenant_id: str
    status: str
    error: str | None = None
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, t: Task) -> TaskOut:
        return cls(
            id=t.id,
            type=t.type,
            tenant_id=t.tenant_id,
            status=t.status,
            error=t.error,
            created_at=fmt_ts(t.created_at),
            updated_at=fmt_ts(t.updated_at),
        )


class TenantPage(BaseModel):
    items: list[TenantOut]
    total: int
    limit: int
    offset: int


class TaskPage(BaseModel):
    items: list[TaskOut]
    total: int
    limit: int
    offset: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
