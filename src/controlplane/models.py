"""Persistence model (PostgreSQL)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # UNIQUE covers every row, including `destroyed` ones: a slug is never reused.
    slug: Mapped[str] = mapped_column(String(28), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Task(Base):
    """A task *is* the event: this row doubles as the transactional outbox entry
    (`published_at IS NULL` means "not yet handed to the broker")."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Safety net behind the tenant status guards: at most one open task per tenant.
        Index(
            "uq_tasks_one_open_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("status IN ('accepted', 'in_progress')"),
        ),
        Index(
            "ix_tasks_unpublished",
            "created_at",
            postgresql_where=text("published_at IS NULL"),
        ),
        Index("ix_tasks_tenant_created", "tenant_id", "created_at"),
    )


class ProcessedUpdate(Base):
    """Idempotency ledger for inbound worker updates (one row per update_id)."""

    __tablename__ = "processed_updates"

    update_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
