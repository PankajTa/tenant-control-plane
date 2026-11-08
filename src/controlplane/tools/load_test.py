"""Concurrency demo against a RUNNING stack (stdlib only).

  make load-test

Proves, over real HTTP with real parallelism, that
  1. N concurrent creates of one slug  -> exactly one 201, the rest 409 tenant_already_exists
  2. N concurrent PATCHes, same version -> exactly one 200, the rest 409
  3. N concurrent DELETEs               -> exactly one 202, the rest 409
The worker must be running with --fail-rate=0 so tenants reach `active`.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

BASE = urlsplit(os.environ.get("BASE_URL", "http://127.0.0.1:8000"))
N = int(os.environ.get("LOAD_N", "20"))


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    conn = http.client.HTTPConnection(BASE.hostname or "127.0.0.1", BASE.port or 80, timeout=30)
    try:
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, payload, {"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else {})
    finally:
        conn.close()


def race(fn) -> list[tuple[int, dict]]:
    barrier = threading.Barrier(N)

    def run(_: int):
        barrier.wait()
        return fn()

    with ThreadPoolExecutor(max_workers=N) as pool:
        return list(pool.map(run, range(N)))


def wait_for_status(tenant_id: str, wanted: str, timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, tenant = call("GET", f"/v1/tenants/{tenant_id}")
        if tenant.get("status") == wanted:
            return tenant
        time.sleep(0.5)
    raise SystemExit(f"FAIL: tenant {tenant_id} never reached '{wanted}'")


def expect(label: str, results: list[tuple[int, dict]], winner: int, loser: int) -> None:
    counts = Counter(status for status, _ in results)
    ok = counts[winner] == 1 and counts[loser] == N - 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {dict(counts)}")
    if not ok:
        sys.exit(1)


def main() -> None:
    slug = f"load-{uuid.uuid4().hex[:8]}"
    results = race(lambda: call("POST", "/v1/tenants", {"slug": slug, "name": "Load Test"}))
    expect(f"{N} concurrent creates of '{slug}'", results, 201, 409)
    tenant = next(body for status, body in results if status == 201)
    assert all(
        b["error"]["code"] == "tenant_already_exists" for s, b in results if s == 409
    ), "losers must report tenant_already_exists"

    tenant = wait_for_status(tenant["id"], "active")
    results = race(
        lambda: call("PATCH", f"/v1/tenants/{tenant['id']}", {"version": tenant["version"], "name": "Renamed"})
    )
    expect(f"{N} concurrent PATCHes with version={tenant['version']}", results, 200, 409)

    tenant = wait_for_status(tenant["id"], "active")
    results = race(lambda: call("DELETE", f"/v1/tenants/{tenant['id']}"))
    expect(f"{N} concurrent DELETEs", results, 202, 409)

    wait_for_status(tenant["id"], "destroyed")
    print("PASS  tenant walked deploy -> update -> destroy; all race conditions handled")


if __name__ == "__main__":
    main()
