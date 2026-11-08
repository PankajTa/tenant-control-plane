import re

import pytest

from conftest import drive

TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def create(client, slug="acme", name="Acme Inc"):
    return client.post("/v1/tenants", json={"slug": slug, "name": name})


def activate(client, session_factory, tenant) -> dict:
    task = client.get(f"/v1/tenants/{tenant['id']}/tasks").json()["items"][0]
    drive(session_factory, task["id"])
    return client.get(f"/v1/tenants/{tenant['id']}").json()


def test_create_returns_tenant_and_task(client):
    r = create(client)
    assert r.status_code == 201
    body = r.json()
    assert r.headers["location"] == f"/v1/tenants/{body['id']}"
    assert body["status"] == "provisioning"
    assert body["version"] == 1
    assert TS.match(body["created_at"]) and TS.match(body["updated_at"])

    task = client.get(f"/v1/tasks/{body['task_id']}").json()
    assert (task["type"], task["status"], task["tenant_id"]) == ("deploy", "accepted", body["id"])


@pytest.mark.parametrize(
    "slug", ["ab", "1abc", "Abc", "abc-", "a" * 29, "ab_c", "", "has space"]
)
def test_invalid_slug_rejected(client, slug):
    r = create(client, slug=slug)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("slug", ["abc", "a-b", "a" * 28, "a1b2c3"])
def test_valid_slugs_accepted(client, slug):
    assert create(client, slug=slug).status_code == 201


def test_blank_name_rejected(client):
    assert create(client, name="   ").status_code == 422


def test_duplicate_slug(client):
    assert create(client).status_code == 201
    r = create(client)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "tenant_already_exists"


def test_slug_stays_taken_after_destroy(client, session_factory):
    t = create(client).json()
    t = activate(client, session_factory, t)
    d = client.delete(f"/v1/tenants/{t['id']}").json()
    drive(session_factory, d["task_id"])
    assert client.get(f"/v1/tenants/{t['id']}").json()["status"] == "destroyed"
    assert create(client).json()["error"]["code"] == "tenant_already_exists"


def test_get_and_not_found(client):
    t = create(client).json()
    assert client.get(f"/v1/tenants/{t['id']}").json()["slug"] == "acme"
    r = client.get("/v1/tenants/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "tenant_not_found"
    r = client.get("/v1/tasks/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "task_not_found"


def test_error_body_is_structured(client):
    err = client.get("/v1/tenants/nope").json()["error"]
    assert set(err) == {"code", "message", "details"}


def test_unknown_route_uses_error_envelope(client):
    r = client.get("/v1/nothing")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_list_filter_and_pagination(client, session_factory):
    ids = [create(client, slug=f"tenant-{i}").json()["id"] for i in range(5)]
    activate(client, session_factory, {"id": ids[0]})

    page = client.get("/v1/tenants?limit=2&offset=0").json()
    assert page["total"] == 5 and len(page["items"]) == 2 and page["limit"] == 2
    page2 = client.get("/v1/tenants?limit=2&offset=2").json()
    assert {t["id"] for t in page["items"]}.isdisjoint({t["id"] for t in page2["items"]})

    active = client.get("/v1/tenants?status=active").json()
    assert [t["id"] for t in active["items"]] == [ids[0]]
    assert client.get("/v1/tenants?status=bogus").status_code == 422
    assert client.get("/v1/tenants?limit=0").status_code == 422


def test_patch_happy_path(client, session_factory, publisher, relay):
    t = activate(client, session_factory, create(client).json())
    relay.run_once()
    before = len(publisher.published)

    r = client.patch(f"/v1/tenants/{t['id']}", json={"version": t["version"], "name": "New"})
    assert r.status_code == 200
    body = r.json()
    assert (body["name"], body["status"], body["version"]) == ("New", "updating", t["version"] + 1)
    assert client.get(f"/v1/tasks/{body['task_id']}").json()["type"] == "update"

    relay.run_once()
    assert len(publisher.published) == before + 1  # exactly one event for the call

    drive(session_factory, body["task_id"])
    final = client.get(f"/v1/tenants/{t['id']}").json()
    assert final["status"] == "active" and final["version"] == body["version"] + 1


def test_patch_stale_version_conflict(client, session_factory):
    t = activate(client, session_factory, create(client).json())
    r = client.patch(f"/v1/tenants/{t['id']}", json={"version": t["version"] + 7, "name": "x"})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "tenant_version_conflict"
    assert err["details"]["current_version"] == t["version"]


def test_patch_not_allowed_unless_active(client):
    t = create(client).json()  # provisioning
    r = client.patch(f"/v1/tenants/{t['id']}", json={"version": t["version"], "name": "x"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "tenant_update_not_allowed"


def test_patch_validation_and_404(client):
    t = create(client).json()
    assert client.patch(f"/v1/tenants/{t['id']}", json={"name": "x"}).status_code == 422
    assert client.patch(f"/v1/tenants/{t['id']}", json={"version": 1}).status_code == 422
    assert (
        client.patch(f"/v1/tenants/{t['id']}", json={"version": 1, "slug": "other"}).status_code
        == 422
    )
    r = client.patch("/v1/tenants/nope", json={"version": 1, "name": "x"})
    assert r.json()["error"]["code"] == "tenant_not_found"


def test_delete_rules(client, session_factory):
    t = create(client).json()
    r = client.delete(f"/v1/tenants/{t['id']}")  # provisioning -> not allowed
    assert r.status_code == 409 and r.json()["error"]["code"] == "tenant_update_not_allowed"

    t = activate(client, session_factory, t)
    r = client.delete(f"/v1/tenants/{t['id']}")
    assert r.status_code == 202
    assert r.json()["status"] == "destroying"
    assert client.get(f"/v1/tasks/{r.json()['task_id']}").json()["type"] == "destroy"

    # second delete while destroying
    assert client.delete(f"/v1/tenants/{t['id']}").status_code == 409
    assert client.delete("/v1/tenants/nope").json()["error"]["code"] == "tenant_not_found"


def test_failed_tenant_can_be_deleted_and_destroyed(client, session_factory):
    t = create(client).json()
    task = client.get(f"/v1/tenants/{t['id']}/tasks").json()["items"][0]
    drive(session_factory, task["id"], "failed")
    failed = client.get(f"/v1/tenants/{t['id']}").json()
    assert failed["status"] == "failed"
    assert client.get(f"/v1/tasks/{task['id']}").json()["error"]

    d = client.delete(f"/v1/tenants/{t['id']}")
    assert d.status_code == 202
    drive(session_factory, d.json()["task_id"])
    assert client.get(f"/v1/tenants/{t['id']}").json()["status"] == "destroyed"


def test_task_listing_filters(client, session_factory):
    a = create(client, slug="aaa").json()
    b = create(client, slug="bbb").json()
    activate(client, session_factory, a)

    assert client.get("/v1/tasks").json()["total"] == 2
    only_a = client.get(f"/v1/tasks?tenant_id={a['id']}").json()
    assert [t["tenant_id"] for t in only_a["items"]] == [a["id"]]
    assert client.get("/v1/tasks?status=accepted").json()["total"] == 1
    assert client.get("/v1/tasks?type=deploy").json()["total"] == 2
    assert client.get("/v1/tasks?type=destroy").json()["total"] == 0
    assert client.get(f"/v1/tenants/{b['id']}/tasks").json()["total"] == 1
    assert client.get("/v1/tenants/nope/tasks").json()["error"]["code"] == "tenant_not_found"


def test_tasks_are_read_only_over_http(client):
    assert client.post("/v1/tasks", json={}).status_code == 405
    assert client.delete("/v1/tasks/x").status_code == 405


def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200
