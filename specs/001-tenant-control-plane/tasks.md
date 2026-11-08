# Tasks: Tenant Provisioning Control Plane
<!-- Phase 4: /speckit.tasks -->
Format: `[ID] [P?] [Story] Description — file`. `[P]` = parallelizable. `[X]` = implemented.
Tasks marked **(verify)** require running the stack; they are NOT yet confirmed (see implementation.md).

## Phase 1: Setup
- [X] T001 Project skeleton, pyproject, ruff/pytest/bandit config — `pyproject.toml`
- [X] T002 [P] Dockerfile (runtime + dev stages) — `Dockerfile`
- [X] T003 [P] Compose stack: postgres, rabbitmq, api, worker — `docker-compose.yml`
- [X] T004 [P] Test compose with throwaway deps — `docker-compose.test.yml`
- [X] T005 [P] Makefile (`up`, `test`, `check`, `format`, `load-test`, `clean`), generated `.env` — `Makefile`, `.env.example`, `.gitignore`

## Phase 2: Foundational (blocks all stories)
- [X] T006 Settings from env — `src/controlplane/config.py`
- [X] T007 [P] Clock/id/timestamp helpers (ms, `Z`) — `src/controlplane/clock.py`
- [X] T008 [P] Domain errors with contract codes — `src/controlplane/errors.py`
- [X] T009 Pure state machine — `src/controlplane/state.py`
- [X] T010 ORM models, partial unique/outbox indexes — `src/controlplane/models.py`
- [X] T011 Engine, sessions, schema bootstrap under advisory lock — `src/controlplane/db.py`
- [X] T012 [P] Async JSON logging — `src/controlplane/logging_config.py`
- [X] T013 Test: state machine tables — `tests/test_state_machine.py`

## Phase 3: US1 + US2 + US3 — Tenant lifecycle & concurrency (P1)
- [X] T014 [US1] Create tenant + deploy task in one tx, UNIQUE slug race — `services/tenants.py`
- [X] T015 [US2] PATCH via conditional UPDATE (version+status) — `services/tenants.py`
- [X] T016 [US2] DELETE guard `active|failed` → destroying — `services/tenants.py`
- [X] T017 [US1] Read services for tenants/tasks — `services/tenants.py`, `services/tasks.py`
- [X] T018 [US3] Tests: concurrent create/PATCH/DELETE/PATCH-vs-DELETE, open-task invariant — `tests/test_concurrency.py`

## Phase 4: US4 — Reliable messaging (P1)
- [X] T019 [P] Wire schemas (`TaskEvent`, `TaskUpdate`) — `messaging/messages.py`
- [X] T020 [P] Topology incl. DLX/DLQ — `messaging/topology.py`
- [X] T021 [P] Backoff with jitter — `messaging/backoff.py`
- [X] T022 Confirmed publisher with reconnect — `messaging/publisher.py`
- [X] T023 Outbox relay (SKIP LOCKED, kick + poll) — `messaging/relay.py`
- [X] T024 Idempotent, order-tolerant update service — `services/updates.py`
- [X] T025 Consumer: dispositions, retry, reconnect — `messaging/consumer.py`
- [X] T026 Tests: updates (dup, stale, terminal-first, unknown) — `tests/test_updates.py`
- [X] T027 Tests: relay (after-commit, rollback, outage, partial failure) — `tests/test_relay.py`
- [X] T028 Tests: consumer (poison, transient, requeue) — `tests/test_consumer.py`

## Phase 5: US5 — HTTP API (P2)
- [X] T029 Request/response schemas, slug regex — `src/controlplane/schemas.py`
- [X] T030 Routes: tenants CRUD, tasks read, nested tasks, health — `api/routes.py`
- [X] T031 App factory, lifespan (relay+consumer), uniform error envelope — `api/app.py`, `api/context.py`
- [X] T032 Entrypoint — `main.py`, `__main__.py`
- [X] T033 Tests: contract, validation, pagination, filters, error shape — `tests/test_tenants_api.py`

## Phase 6: US6 — Worker simulator & scenario tooling (P2)
- [X] T034 Worker config (CLI + env) — `src/worker_sim/config.py`
- [X] T035 Worker: pure `plan()`, run loop, dedupe — `src/worker_sim/worker.py`, `__main__.py`
- [X] T036 [P] Direct-publish tool (dupes, poison) — `tools/publish_update.py`
- [X] T037 [P] HTTP race demo — `tools/load_test.py`
- [X] T038 Tests: worker plan/CLI — `tests/test_worker_sim.py`
- [X] T039 Test: async logging — `tests/test_logging.py`
- [X] T040 Test: end-to-end through real RabbitMQ (happy, failing, chaos) — `tests/test_e2e.py`

## Phase 7: Polish & delivery
- [X] T041 Quality gate script — `scripts/check.sh`
- [X] T042 CI workflow — `.github/workflows/ci.yml`
- [X] T043 README (architecture, trade-offs, API, scenarios) — `README.md`
- [X] T044 [P] Kubernetes example + AWS mapping notes — `deploy/k8s/controlplane.yaml`, README
- [X] T045 Spec Kit artifacts — `.specify/`, `specs/001-tenant-control-plane/`
- [ ] T046 **(verify)** `make format` then `make check` passes on a clean machine
- [ ] T047 **(verify)** `make up` then `make load-test` shows exactly-one-winner results
- [ ] T048 **(verify)** Adjust coverage gate (`fail_under`) to measured coverage
- [ ] T049 Push to public GitHub repo with several logical commits

## Dependencies
Phase 1 → 2 → (3, 4 in parallel after T011) → 5 (needs 3, 4) → 6 (needs 4) → 7.
Within phases, `[P]` tasks touch different files.

## Story → Test traceability
| Story | Tests |
|---|---|
| US1 | test_tenants_api, test_e2e |
| US2 | test_tenants_api, test_updates, test_e2e |
| US3 | test_concurrency, `make load-test` |
| US4 | test_relay, test_updates, test_consumer, test_e2e |
| US5 | test_tenants_api |
| US6 | test_worker_sim, test_e2e |
