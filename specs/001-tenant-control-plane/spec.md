# Feature Specification: Tenant Provisioning Control Plane
<!-- Phase 2 of Spec-Driven Development: /speckit.specify  (WHAT and WHY, not HOW) -->

**Feature Branch**: `001-tenant-control-plane`
**Created**: 2026-11-08 | **Status**: Implemented (see `implementation.md`)
**Input**: Take-home brief "Tenant Provisioning Control Plane"

## Clarifications (resolved ambiguities)
| # | Question | Decision |
|---|----------|----------|
| 1 | Which error wins when a PATCH has a stale version *and* the tenant is not active? | Stale version is reported first (`tenant_version_conflict`), so the loser of a same-version race gets the conflict code. |
| 2 | A terminal worker update arrives before `in_progress`? | Apply it (task jumps to terminal); the late `in_progress` is ignored as stale. Dropping it would strand the task forever. |
| 3 | Success status codes? | POST 201 (+Location), PATCH 200, DELETE 202 (tenant not yet gone), reads 200. |
| 4 | Where does the client send the optimistic-lock token? | `version` in the PATCH body (required). |
| 5 | Can a slug be reused after destroy? | No. Slugs are unique across all tenants, including `destroyed`. |
| 6 | Are updates for unknown tasks retried? | No; they are dead-lettered (the task row always exists before its event is published). |

## User Scenarios & Testing

### User Story 1 - Provision a tenant end to end (P1)
A platform operator creates a tenant and, with no manual steps, watches it become usable.
**Why P1**: this is the product's core value.
**Independent Test**: create a tenant, poll until `active`, inspect the task history.
**Acceptance Scenarios**
1. **Given** no tenant `acme`, **When** I create it, **Then** I get the tenant in `provisioning` (version 1) and a `deploy` task in `accepted`.
2. **Given** the worker is running, **When** time passes, **Then** the task goes `accepted ? in_progress ? done` and the tenant becomes `active` with a higher `version`.
3. **Given** the worker always fails, **When** I create a tenant, **Then** the task ends `failed` and the tenant ends `failed`.

### User Story 2 - Change and retire a tenant (P1)
**Independent Test**: PATCH an active tenant, then DELETE it.
1. **Given** an `active` tenant, **When** I PATCH with its current `version`, **Then** it becomes `updating`, `version` increments, an `update` task is created, and on success it returns to `active`.
2. **Given** an `active` or `failed` tenant, **When** I DELETE it, **Then** it becomes `destroying`, a `destroy` task is created, and on success it becomes `destroyed`.
3. **Given** a tenant in any other status, **When** I PATCH or DELETE it, **Then** I get `tenant_update_not_allowed`.

### User Story 3 - Safe under concurrency (P1)
**Independent Test**: fire N simultaneous requests.
1. **Given** N concurrent creates with one slug, **Then** exactly one succeeds; the rest get `tenant_already_exists`.
2. **Given** N concurrent PATCHes with the same `version`, **Then** exactly one succeeds.
3. **Given** a PATCH racing a DELETE, **Then** at most one wins.
4. A tenant never has more than one open (`accepted`/`in_progress`) task.

### User Story 4 - Reliable messaging (P1)
1. **Given** a committed write, **Then** exactly one event is published, after the commit; a rolled-back write publishes nothing.
2. **Given** the broker is down, **Then** events are kept and published when it returns.
3. **Given** the same update delivered twice, **Then** nothing changes and nothing fails.
4. **Given** `in_progress` arrives after `done` (or any update for a terminal task), **Then** state does not regress.
5. **Given** a malformed/unknown-task message, **Then** it is set aside for inspection and the consumer keeps running.
6. **Given** a transient database/broker failure, **Then** processing is retried with backoff and no message is lost.

### User Story 5 - Observe and read (P2)
Operators can list/get tenants and tasks, filter, and paginate; every failure returns a structured, machine-readable body.

### User Story 6 - Reproduce failure scenarios (P2)
By restarting the worker with different arguments (`--fail-rate`, delays, duplicates, reordering) or by publishing messages directly, an engineer can reproduce failures, duplicates and out-of-order delivery.

### Edge Cases
- Slug violating `^[a-z][-a-z0-9]{1,26}[a-z0-9]$`; blank name; unknown fields; PATCH with no changes ? validation error.
- Unknown tenant/task ids ? `tenant_not_found` / `task_not_found`.
- Process crash after commit but before publish; crash after publish but before marking published (duplicate event).
- Worker crash mid-task (task redelivered).
- Terminal update that overtakes `in_progress`.
- Restart: all tenants survive.

## Requirements

### Functional
- **FR-001** Tenants have server-generated `id`, unique `slug`, non-empty `name`, `status`, integer `version`, ISO-8601 ms `Z` timestamps.
- **FR-002** `version` increments on every mutation, including worker-applied status changes.
- **FR-003** Tenant status machine: provisioning?active|failed; active?updating|destroying; updating?active|failed; destroying?destroyed|failed; failed?destroying.
- **FR-004** Task status machine: accepted?in_progress?done|failed; done/failed terminal.
- **FR-005** Tasks are created only as a side effect of tenant create/update/delete; at most one open task per tenant.
- **FR-006** HTTP: tenants CRUD (create, list, get, partial update, delete); tasks list/get only. Conventional REST status codes; documented pagination/filtering.
- **FR-007** Structured errors with codes `tenant_not_found`, `tenant_already_exists`, `tenant_update_not_allowed`, `tenant_version_conflict`, `task_not_found`.
- **FR-008** Outbound: exactly one event per state-changing call, after durable commit; the task is the event (`id`, `type`, `tenant_id`, `status` recoverable).
- **FR-009** Inbound: worker updates carry an idempotency key and task reference; consumer is idempotent, order-tolerant, resilient.
- **FR-010** A worker simulator (separate process) with startup-configurable failure rate and delays that publishes `in_progress` then `done`/`failed`.
- **FR-011** Slug uniqueness includes destroyed tenants.

### Non-Functional
- **NFR-001** Concurrent same-version PATCHes never both succeed.
- **NFR-002** Tenants survive restart.
- **NFR-003** Go or Python; runs locally in containers; one boot command, one test command.
- **NFR-004** Quality gates: lint, formatter, security scan, automated tests covering state machine, concurrency, messaging.
- **NFR-005** README with architecture, trade-offs, API examples, setup. No secrets in repo.

### Key Entities
- **Tenant**: customer environment mutated through tasks.
- **Task**: asynchronous operation on a tenant; persisted form of the published event.
- **Worker update**: progress message `{update_id, task_id, status}`.

## Success Criteria
- **SC-001** A created tenant reaches `active` with no manual steps.
- **SC-002** In stress runs (?16 parallel requests) exactly one of each racing set succeeds.
- **SC-003** Replaying or reordering updates leaves tenant/task state identical to the clean run.
- **SC-004** `make up`, `make test`, `make check` work from a cold clone.

## Out of Scope
Authentication/authorization, UI, metrics/tracing, multi-region, real provisioning.
