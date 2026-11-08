# REST contract
Base path `/v1`. JSON. Timestamps ISO-8601 ms `Z`.

| Method & path | Success | Request | Errors |
|---|---|---|---|
| POST /tenants | 201 + `Location` | `{slug, name}` | 409 tenant_already_exists · 422 |
| GET /tenants | 200 | `?status&limit(1-200,def 50)&offset` | 422 |
| GET /tenants/{id} | 200 | | 404 tenant_not_found |
| PATCH /tenants/{id} | 200 | `{version, name}` | 404 · 409 tenant_version_conflict · 409 tenant_update_not_allowed · 422 |
| DELETE /tenants/{id} | 202 | | 404 · 409 tenant_update_not_allowed |
| GET /tenants/{id}/tasks | 200 | `?status&type&limit&offset` | 404 tenant_not_found |
| GET /tasks | 200 | `?tenant_id&status&type&limit&offset` | 422 |
| GET /tasks/{id} | 200 | | 404 task_not_found |
| GET /healthz, /readyz | 200 / 503 | | |

Mutating responses = tenant + `task_id`. Lists = `{items,total,limit,offset}`, newest first.
Error body: `{"error":{"code","message","details"}}`; also `validation_error` 422, `not_found` 404,
`method_not_allowed` 405, `internal_error` 500.
