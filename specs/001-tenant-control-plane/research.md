# Research & Decisions (supports plan.md)

| Decision | Choice | Alternatives considered | Why |
|---|---|---|---|
| Language/framework | Python 3.12, FastAPI, Pydantic v2 | Go + chi | Fast to write correctly; typed validation gives the 422 contract for free |
| Database | PostgreSQL 16 | SQLite, MySQL | Real row locks, partial unique indexes, `SKIP LOCKED`, `ON CONFLICT` |
| ORM | SQLAlchemy 2.0 (sync) + psycopg3 | async SQLAlchemy | Sync is simpler to reason about; FastAPI runs sync handlers in a threadpool |
| Broker | RabbitMQ (pika) | Kafka, Redis streams, SQS | Per-message ack/nack, DLX, publisher confirms, trivial in Compose; `EventPublisher` seam allows SQS/SNS |
| Event durability | Transactional outbox (`tasks.published_at`) | Publish inline after commit | Inline loses the event on a crash between commit and publish |
| Optimistic lock | One conditional `UPDATE … WHERE version AND status` | `SELECT … FOR UPDATE`, ORM version_id_col | Single atomic statement, no read-modify-write window, easy to explain |
| Idempotency | Ledger table `processed_updates(update_id PK)` + `ON CONFLICT DO NOTHING` in the same tx as the state change | In-memory set, Redis | Survives restarts; atomic with the effect |
| Ordering | Lock task row, then tenant row (fixed lock order) | Global lock | No deadlock; HTTP path only locks tenant and inserts new task |
| Poison handling | `nack requeue=false` → dead-letter exchange/queue | Drop, infinite requeue | Inspectable, never blocks the queue |
| Logging | `QueueHandler`/`QueueListener`, JSON lines | Sync logging | Logging cannot block hot paths |
| Schema management | `create_all` under advisory lock | Alembic | Adequate for scope; documented trade-off |
| Pagination | limit/offset + total | Keyset cursor | Simple, predictable; noted as limitation |
| Tooling | ruff (lint+format), bandit, pytest-cov, Docker Compose, Make | tox, poetry | Few moving parts; one command runner |
