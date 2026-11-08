"""Inbound update semantics: idempotent, order-tolerant, atomic."""

import pytest
from sqlalchemy import func, select

from conftest import send
from controlplane.errors import UnknownTaskError
from controlplane.models import ProcessedUpdate, Task, Tenant
from controlplane.services.updates import Outcome


def snapshot(session_factory, tenant_id, task_id):
    with session_factory() as s:
        return s.get(Tenant, tenant_id), s.get(Task, task_id)


@pytest.fixture()
def deploy(tenants):
    return tenants.create_tenant("acme", "Acme")


def test_full_happy_path(session_factory, deploy):
    tenant, task = deploy
    assert send(session_factory, task.id, "in_progress").outcome == Outcome.APPLIED
    t, k = snapshot(session_factory, tenant.id, task.id)
    assert (k.status, t.status, t.version) == ("in_progress", "provisioning", 1)

    r = send(session_factory, task.id, "done")
    assert (r.outcome, r.task_status, r.tenant_status) == (Outcome.APPLIED, "done", "active")
    t, k = snapshot(session_factory, tenant.id, task.id)
    assert (k.status, t.status, t.version) == ("done", "active", 2)  # version bumped by worker


def test_failed_outcome_fails_tenant_and_records_error(session_factory, deploy):
    tenant, task = deploy
    send(session_factory, task.id, "in_progress")
    send(session_factory, task.id, "failed", error="boom")
    t, k = snapshot(session_factory, tenant.id, task.id)
    assert (k.status, k.error, t.status) == ("failed", "boom", "failed")


def test_duplicate_update_is_a_noop(session_factory, deploy):
    tenant, task = deploy
    send(session_factory, task.id, "in_progress", update_id="u1")
    again = send(session_factory, task.id, "in_progress", update_id="u1")
    assert again.outcome == Outcome.DUPLICATE
    send(session_factory, task.id, "done", update_id="u2")
    t_before, _ = snapshot(session_factory, tenant.id, task.id)

    assert send(session_factory, task.id, "done", update_id="u2").outcome == Outcome.DUPLICATE
    t_after, _ = snapshot(session_factory, tenant.id, task.id)
    assert t_after.version == t_before.version  # nothing changed
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(ProcessedUpdate)) == 2


def test_stale_in_progress_after_done_does_not_regress(session_factory, deploy):
    tenant, task = deploy
    send(session_factory, task.id, "in_progress")
    send(session_factory, task.id, "done")
    r = send(session_factory, task.id, "in_progress", update_id="late")
    assert r.outcome == Outcome.STALE
    t, k = snapshot(session_factory, tenant.id, task.id)
    assert (k.status, t.status) == ("done", "active")


def test_update_for_terminal_task_is_ignored(session_factory, deploy):
    tenant, task = deploy
    send(session_factory, task.id, "in_progress")
    send(session_factory, task.id, "done")
    r = send(session_factory, task.id, "failed", update_id="contradiction")
    assert r.outcome == Outcome.STALE
    t, k = snapshot(session_factory, tenant.id, task.id)
    assert (k.status, t.status, t.version) == ("done", "active", 2)


def test_terminal_before_in_progress_is_tolerated(session_factory, deploy):
    tenant, task = deploy
    assert send(session_factory, task.id, "done").outcome == Outcome.APPLIED
    assert send(session_factory, task.id, "in_progress").outcome == Outcome.STALE
    t, k = snapshot(session_factory, tenant.id, task.id)
    assert (k.status, t.status) == ("done", "active")


def test_unknown_task_raises_and_records_nothing(session_factory):
    with pytest.raises(UnknownTaskError):
        send(session_factory, "no-such-task", "done")
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(ProcessedUpdate)) == 0


def test_update_and_destroy_tasks_drive_the_tenant(tenants, session_factory):
    tenant, deploy_task = tenants.create_tenant("cycle", "Cycle")
    send(session_factory, deploy_task.id, "done")
    t = tenants.get_tenant(tenant.id)

    _, upd = tenants.update_tenant(t.id, t.version, "Renamed")
    send(session_factory, upd.id, "failed", error="nope")
    assert tenants.get_tenant(t.id).status == "failed"

    _, destroy = tenants.delete_tenant(t.id)  # failed -> destroying
    assert tenants.get_tenant(t.id).status == "destroying"
    send(session_factory, destroy.id, "done")
    assert tenants.get_tenant(t.id).status == "destroyed"
