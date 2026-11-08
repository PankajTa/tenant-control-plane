"""Race conditions, exercised with real threads against real PostgreSQL row locking."""

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from conftest import drive, send
from controlplane.errors import (
    DomainError,
    TenantAlreadyExists,
    TenantUpdateNotAllowed,
    TenantVersionConflict,
)
from controlplane.messaging.messages import TaskUpdate
from controlplane.models import Task, Tenant
from controlplane.services.updates import Outcome, apply_update

N = 16


def race(fn, n=N):
    barrier = threading.Barrier(n)

    def run(i):
        barrier.wait()
        try:
            return fn(i)
        except DomainError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(run, range(n)))


def test_concurrent_creates_same_slug_exactly_one_wins(tenants, session_factory):
    results = race(lambda _: tenants.create_tenant("racer", "Racer"))
    wins = [r for r in results if isinstance(r, tuple)]
    losers = [r for r in results if isinstance(r, TenantAlreadyExists)]
    assert len(wins) == 1 and len(losers) == N - 1
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Tenant)) == 1
        assert s.scalar(select(func.count()).select_from(Task)) == 1  # losers left no task behind


def _active_tenant(tenants, session_factory):
    tenant, task = tenants.create_tenant("patchme", "Patch Me")
    drive(session_factory, task.id)
    return tenants.get_tenant(tenant.id)


def test_concurrent_patch_same_version_exactly_one_wins(tenants, session_factory):
    t = _active_tenant(tenants, session_factory)
    results = race(lambda i: tenants.update_tenant(t.id, t.version, f"name-{i}"))
    wins = [r for r in results if isinstance(r, tuple)]
    losers = [r for r in results if isinstance(r, TenantVersionConflict | TenantUpdateNotAllowed)]
    assert len(wins) == 1 and len(losers) == N - 1
    after = tenants.get_tenant(t.id)
    assert after.version == t.version + 1 and after.status == "updating"
    with session_factory() as s:
        update_tasks = s.scalar(select(func.count()).select_from(Task).where(Task.type == "update"))
    assert update_tasks == 1


def test_concurrent_delete_exactly_one_wins(tenants, session_factory):
    t = _active_tenant(tenants, session_factory)
    results = race(lambda _: tenants.delete_tenant(t.id))
    assert sum(isinstance(r, tuple) for r in results) == 1
    assert sum(isinstance(r, TenantUpdateNotAllowed) for r in results) == N - 1


def test_patch_and_delete_race_never_both_win(tenants, session_factory):
    t = _active_tenant(tenants, session_factory)

    def op(i):
        if i % 2:
            return tenants.update_tenant(t.id, t.version, "x")
        return tenants.delete_tenant(t.id)

    results = race(op, n=8)
    assert sum(isinstance(r, tuple) for r in results) == 1


def test_one_open_task_per_tenant_invariant(tenants, session_factory):
    t = _active_tenant(tenants, session_factory)
    tenants.update_tenant(t.id, t.version, "x")
    with session_factory() as s:
        open_tasks = s.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.tenant_id == t.id, Task.status.in_(["accepted", "in_progress"]))
        )
    assert open_tasks == 1


def test_same_update_delivered_concurrently_applies_once(tenants, session_factory):
    _, task = tenants.create_tenant("dupes", "Dupes")
    msg = TaskUpdate(update_id="same-id", task_id=task.id, status="in_progress")
    results = race(lambda _: apply_update(session_factory, msg))
    outcomes = Counter(r.outcome for r in results)
    assert outcomes == {Outcome.APPLIED: 1, Outcome.DUPLICATE: N - 1}


def test_concurrent_terminal_updates_for_one_task_apply_once(tenants, session_factory):
    tenant, task = tenants.create_tenant("terminals", "T")
    send(session_factory, task.id, "in_progress")

    def deliver(i):
        status = "done" if i % 2 else "failed"
        return send(session_factory, task.id, status, update_id=f"u-{i}")

    results = race(deliver)
    assert sum(r.outcome == Outcome.APPLIED for r in results) == 1
    final_tenant = tenants.get_tenant(tenant.id)
    assert final_tenant.version == 2  # bumped exactly once by the terminal outcome
    assert final_tenant.status in {"active", "failed"}
