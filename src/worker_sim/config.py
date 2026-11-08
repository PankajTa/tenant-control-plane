from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerConfig:
    fail_rate: float = 0.0
    min_delay_ms: int = 500
    max_delay_ms: int = 2000
    duplicate_rate: float = 0.0
    out_of_order_rate: float = 0.0
    seed: int | None = None


def parse_args(
    argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None
) -> WorkerConfig:
    """CLI flags win; env vars (WORKER_*) provide the defaults."""
    env = os.environ if env is None else env
    p = argparse.ArgumentParser(
        prog="worker_sim", description="Simulated tenant provisioning worker."
    )
    p.add_argument("--fail-rate", type=float, default=float(env.get("WORKER_FAIL_RATE", 0)),
                   help="probability [0..1] that a task ends `failed` (default 0)")
    p.add_argument("--min-delay-ms", type=int, default=int(env.get("WORKER_MIN_DELAY_MS", 500)),
                   help="min simulated work time per task")
    p.add_argument("--max-delay-ms", type=int, default=int(env.get("WORKER_MAX_DELAY_MS", 2000)),
                   help="max simulated work time per task")
    p.add_argument("--duplicate-rate", type=float, default=float(env.get("WORKER_DUPLICATE_RATE", 0)),
                   help="probability [0..1] that each update is published twice (same update_id)")
    p.add_argument("--out-of-order-rate", type=float,
                   default=float(env.get("WORKER_OUT_OF_ORDER_RATE", 0)),
                   help="probability [0..1] that the terminal update is sent BEFORE in_progress")
    p.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible runs")
    a = p.parse_args(argv)

    for name in ("fail_rate", "duplicate_rate", "out_of_order_rate"):
        if not 0.0 <= getattr(a, name) <= 1.0:
            p.error(f"--{name.replace('_', '-')} must be between 0 and 1")
    if a.min_delay_ms < 0 or a.max_delay_ms < a.min_delay_ms:
        p.error("need 0 <= --min-delay-ms <= --max-delay-ms")
    return WorkerConfig(
        fail_rate=a.fail_rate,
        min_delay_ms=a.min_delay_ms,
        max_delay_ms=a.max_delay_ms,
        duplicate_rate=a.duplicate_rate,
        out_of_order_rate=a.out_of_order_rate,
        seed=a.seed,
    )
