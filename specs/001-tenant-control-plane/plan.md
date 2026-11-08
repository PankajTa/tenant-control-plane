# Implementation Plan: Tenant Provisioning Control Plane
<!-- Phase 3: /speckit.plan  (HOW) -->
**Branch**: `001-tenant-control-plane` | **Spec**: [spec.md](spec.md)

## Summary
A FastAPI service backed by PostgreSQL. Each mutation is one transaction writing tenant + task; the
task row doubles as a transactional-outbox entry that a relay thread publishes to RabbitMQ after
commit. A consumer thread applies worker updates idempotently through a ledger table. A separate
worker-simulator process closes the loop. Everything is booted by Docker Compose.

## Technical Context
- **Language**: Python 3.12 · **Web**: FastAPI + Pydantic v2 · **DB**: PostgreSQL 16 (SQLAlchemy 2, psycopg3)
- **Broker**: RabbitMQ 3.13 (pika, publisher confirms) · **Testing**: pytest + pytest-cov, real Postgres/RabbitMQ in containers
- **Quality**: ruff (lint+format), bandit · **Runner**: Make + Docker Compose
- **Scale**: single-digit replicas; outbox `SKIP LOCKED` and idempotent consumers make replicas safe
- **Constraints**: no secrets in repo; one-command boot and test; runs locally

## Constitution Check
| Principle | How the plan satisfies it | Status |
|---|---|---|
| I Correctness over breadth | No auth/UI/metrics; effort on state, concurrency, messaging | ✅ |
| II State machine is law | `state.py` pure + table tests | ✅ |
| III At-least-once | Ledger, stale-ignore, DLQ, backoff | ✅ |
| IV DB arbitrates | UNIQUE, conditional UPDATE, row locks, thread tests on Postgres | ✅ |
| V Publish only durable | Transactional outbox | ✅ |
| VI Boring code | Sync SQLAlchemy, plain threads, no framework magic | ✅ |
| VII No secrets | env config, generated `.env` | ✅ |
| VIII One command | `make up/test/check` | ✅ |
| IX Observable | async JSON logging, `/healthz` `/readyz` | ✅ |

Re-check after design: ✅ no violations.

## Project Structure
```
.specify/memory/constitution.md
specs/001-tenant-control-plane/{spec,plan,research,data-model,tasks,implementation,quickstart}.md, contracts/
src/controlplane/
  state.py            # pure state machine
  models.py db.py config.py clock.py errors.py schemas.py logging_config.py main.py
  services/{tenants,tasks,updates}.py
  messaging/{topology,messages,publisher,relay,consumer,backoff}.py
  api/{app,routes,context}.py
  tools/{publish_update,load_test}.py
src/worker_sim/{config,worker,__main__}.py
tests/                # unit, DB-backed, concurrency, e2e
Dockerfile docker-compose.yml docker-compose.test.yml Makefile scripts/check.sh .github/workflows/ci.yml
deploy/k8s/controlplane.yaml
```
**Structure decision**: one installable package + a second small package for the worker so the two
processes share only the wire schema and topology.

## Design Phases
1. **Foundations** – config, clock, errors, state machine, models, DB bootstrap.
2. **Write path** – tenant service with conditional UPDATE / UNIQUE-based guards (US1–US3).
3. **Messaging** – outbox relay, publisher, topology, update service, consumer (US4).
4. **HTTP** – routes, schemas, error envelope, health (US5).
5. **Worker simulator & tools** – plan/run, CLI, publish tool, load test (US1, US6).
6. **Quality & delivery** – tests, Docker/Compose, Make, CI, README, k8s notes.

## Risks & Mitigations
| Risk | Mitigation |
|---|---|
| Crash between commit and publish | Outbox + poll |
| Crash between publish and mark | Duplicate event tolerated by design |
| Deadlock between API and consumer | Fixed lock order task→tenant; API never locks tasks |
| Stuck task from reordered terminal update | Apply terminal over `accepted` (spec clarification 2) |
| Formatter drift on first run | `make format` documented |

## Complexity Tracking
No constitution violations to justify.
