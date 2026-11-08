# Tenant Control Plane Constitution
<!-- Phase 1 of Spec-Driven Development: /speckit.constitution -->

## Core Principles

### I. Correctness Over Breadth
State machine, concurrency and messaging correctness take priority over features. Nothing is added
"for completeness" if it dilutes those three. Scope creep (auth, UI, metrics) is rejected in review.

### II. The State Machine Is Law
All tenant and task transitions live in one pure, I/O-free module (`state.py`). Every transition
and every rejected transition is table-tested. No endpoint or consumer may change status except
through it.

### III. Design For At-Least-Once
"Exactly-once" does not exist. Every producer may re-send; every consumer must be idempotent
(stable idempotency key), order-tolerant (stale input is ignored, never regresses state) and
resilient (transient faults retried with backoff, poison messages dead-lettered, never fatal).

### IV. The Database Arbitrates Concurrency
Races are resolved by the database (UNIQUE constraints, conditional UPDATE, row locks), never by
application-level locks or read-then-write. Concurrency rules are proven with real threads against
real PostgreSQL, not mocks.

### V. Publish Only What Is Durable
An event is published only after the write that caused it has committed (transactional outbox).
Never before commit, never on rollback.

### VI. Boring, Readable Code
Prefer explicit, small, well-named code over clever abstractions. Every line must be explainable
live. Third-party libraries only where they remove risk.

### VII. No Secrets In The Repo
Configuration comes from environment variables. Local credentials are generated at first run into
a git-ignored `.env`.

### VIII. One Command To Run, One To Verify
`make up` boots everything; `make test` runs the suite; `make check` runs every quality gate
(lint, format, security scan, tests+coverage). Everything runs locally in containers.

### IX. Observable By Default
Structured JSON logs, written asynchronously so logging never blocks request or consumer paths.
Health/readiness endpoints exist.

## Quality Gates
- Lint (ruff), format (ruff format), security scan (bandit), tests with coverage threshold.
- A change is not done until `make check` passes.
- Tests must cover: state machine, concurrency rules, messaging behaviour.

## Governance
This constitution supersedes other practices. Amendments require updating this file with a
rationale and re-running the Constitution Check in `plan.md`.

**Version**: 1.0.0 | **Ratified**: 2026-11-08 | **Last Amended**: 2026-11-08
