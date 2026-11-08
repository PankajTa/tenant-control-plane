import pytest

from controlplane.config import BrokerSettings
from controlplane.messaging.messages import TaskEvent
from worker_sim.config import WorkerConfig, parse_args
from worker_sim.worker import Worker

EVENT = TaskEvent(
    id="task-1",
    type="deploy",
    tenant_id="tenant-1",
    status="accepted",
    created_at="2026-01-01T00:00:00.000Z",
    updated_at="2026-01-01T00:00:00.000Z",
)


def worker(**kw) -> Worker:
    cfg = WorkerConfig(min_delay_ms=100, max_delay_ms=100, seed=1, **kw)
    return Worker(cfg, BrokerSettings(amqp_url="amqp://unused"))


def test_happy_plan_is_in_progress_then_done():
    steps = worker().plan(EVENT)
    assert [s.update.status for s in steps] == ["in_progress", "done"]
    assert [s.delay_s for s in steps] == [0.0, 0.1]
    assert all(s.update.task_id == "task-1" for s in steps)


def test_fail_rate_one_always_fails_with_error():
    steps = worker(fail_rate=1.0).plan(EVENT)
    assert steps[-1].update.status == "failed" and steps[-1].update.error


def test_update_ids_are_stable_idempotency_keys():
    a = [s.update.update_id for s in worker().plan(EVENT)]
    b = [s.update.update_id for s in worker().plan(EVENT)]
    assert a == b == ["task-1:in_progress", "task-1:done"]


def test_duplicates_reuse_the_same_update_id():
    steps = worker(duplicate_rate=1.0).plan(EVENT)
    assert [s.update.update_id for s in steps] == [
        "task-1:in_progress",
        "task-1:in_progress",
        "task-1:done",
        "task-1:done",
    ]


def test_out_of_order_sends_terminal_first():
    steps = worker(out_of_order_rate=1.0).plan(EVENT)
    assert [s.update.status for s in steps] == ["done", "in_progress"]


def test_cli_defaults_and_overrides():
    cfg = parse_args(["--fail-rate=1", "--min-delay-ms=5", "--max-delay-ms=10"], env={})
    assert (cfg.fail_rate, cfg.min_delay_ms, cfg.max_delay_ms) == (1.0, 5, 10)
    cfg = parse_args([], env={"WORKER_FAIL_RATE": "0.5"})
    assert cfg.fail_rate == 0.5
    cfg = parse_args(["--fail-rate=0.1"], env={"WORKER_FAIL_RATE": "0.5"})
    assert cfg.fail_rate == 0.1  # CLI beats env


@pytest.mark.parametrize(
    "argv", [["--fail-rate=2"], ["--min-delay-ms=10", "--max-delay-ms=5"], ["--duplicate-rate=-1"]]
)
def test_cli_rejects_bad_values(argv):
    with pytest.raises(SystemExit):
        parse_args(argv, env={})
