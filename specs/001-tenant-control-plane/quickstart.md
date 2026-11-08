# Quickstart / validation scenarios
```bash
make up && make test && make check
curl -s -X POST localhost:8000/v1/tenants -H 'content-type: application/json' -d '{"slug":"acme","name":"Acme"}'
curl -s localhost:8000/v1/tenants                # → active after a couple of seconds
make load-test                                   # concurrency demo (SC-002)
WORKER_FAIL_RATE=1 docker compose up -d worker   # failure scenario (US1.3)
docker compose run --rm worker --duplicate-rate=1 --out-of-order-rate=1   # SC-003
```
Each spec user story maps to tests listed in `tasks.md`.
