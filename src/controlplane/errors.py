"""Domain errors. `code` is the machine-readable contract; HTTP status is chosen per error."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status_code = 400
    code = "error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class TenantNotFound(DomainError):
    status_code = 404
    code = "tenant_not_found"


class TaskNotFound(DomainError):
    status_code = 404
    code = "task_not_found"


class TenantAlreadyExists(DomainError):
    status_code = 409
    code = "tenant_already_exists"


class TenantUpdateNotAllowed(DomainError):
    status_code = 409
    code = "tenant_update_not_allowed"


class TenantVersionConflict(DomainError):
    status_code = 409
    code = "tenant_version_conflict"


class UnknownTaskError(Exception):
    """Inbound update references a task we have never seen (not an HTTP error)."""
