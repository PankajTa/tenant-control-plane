# Messaging contract (RabbitMQ)
Exchange `controlplane` (direct, durable); dead-letter exchange `controlplane.dlx`.

## Outbound: control plane → worker
Routing key `task.created` → queue `worker.tasks`. Persistent, publisher-confirmed, `mandatory`.
```json
{"id":"<task id = event id>","type":"deploy|update|destroy","tenant_id":"…","status":"accepted",
 "created_at":"…Z","updated_at":"…Z"}
```
Guarantee: published once after commit in normal operation; **at-least-once** under crashes.

## Inbound: worker → control plane
Routing key `task.update` → queue `controlplane.task-updates` (DLX → `controlplane.task-updates.dlq`).
```json
{"update_id":"<idempotency key>","task_id":"…","status":"in_progress|done|failed","error":null,"occurred_at":"…Z"}
```
| Situation | Disposition |
|---|---|
| Applied / duplicate / stale | ack |
| Invalid JSON/schema, unknown task, unexpected handler bug | nack(requeue=false) → DLQ |
| DB/pool error after in-process retries | nack(requeue=true) after delay |
| Connection loss | reconnect with exponential backoff + jitter |

Worker idempotency keys are `<task_id>:<status>` (deterministic across redelivery).
