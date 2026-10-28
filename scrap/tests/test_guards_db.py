"""Database-backed tests for idempotency, weigh/delivery guards, stock corrections and roles.

Skipped unless SCRAP_TEST_DATABASE_URL is set. Every test uses fresh codes so reruns
against the same database do not collide.
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from scrap.config import Settings, load_settings
from scrap.api.app import create_app
from scrap.db import Database

DATABASE_URL = os.environ.get("SCRAP_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="SCRAP_TEST_DATABASE_URL is not set")

OWNER = {"X-Actor": "ops", "X-Actor-Role": "owner"}


def u(prefix="", n=8):
    return prefix + uuid.uuid4().hex[:n].upper()


def hdr(role="owner", actor="ops", key=None):
    h = {"X-Actor": actor, "X-Actor-Role": role}
    if key is not None:
        h["Idempotency-Key"] = key
    return h


def new_key():
    return "k-" + uuid.uuid4().hex


@pytest.fixture(scope="module")
def client():
    s = load_settings(allow_anonymous=True)
    s.database_url = DATABASE_URL
    app = create_app(settings=s)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def db():
    database = Database(DATABASE_URL)
    yield database
    database.close()


@pytest.fixture
def material(client):
    code = u("MT")
    r = client.post("/api/materials", json={"code": code, "name": "Copper", "category": "metal"}, headers=OWNER)
    assert r.status_code == 201
    return code


@pytest.fixture
def warehouse(client):
    code = u("WH")
    r = client.post("/api/warehouses", json={"code": code, "name": "Yard"}, headers=OWNER)
    assert r.status_code == 201
    return code


def make_load(client, material_code, truck=None):
    r = client.post("/api/loads", json={"truck_ref": truck or u("TRK-"), "material_code": material_code}, headers=OWNER)
    assert r.status_code == 201
    return r.json()["load_id"]


def count(db, sql, params):
    return db.fetch_one(sql, params)[0]


# -- load creation -----------------------------------------------------------

def test_load_retry_with_same_key_returns_original(client, db, material):
    truck = u("TRK-")
    key = new_key()
    body = {"truck_ref": truck, "material_code": material}
    first = client.post("/api/loads", json=body, headers=hdr(key=key))
    again = client.post("/api/loads", json=body, headers=hdr(key=key))
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["load_id"] == first.json()["load_id"]
    assert count(db, "SELECT count(*) FROM scrap_loads WHERE truck_ref = %s", (truck,)) == 1


def test_load_same_key_different_body_is_refused(client, db, material):
    truck = u("TRK-")
    key = new_key()
    assert client.post("/api/loads", json={"truck_ref": truck, "material_code": material}, headers=hdr(key=key)).status_code == 201
    r = client.post("/api/loads", json={"truck_ref": truck, "material_code": material, "origin": "elsewhere"}, headers=hdr(key=key))
    assert r.status_code == 409
    assert count(db, "SELECT count(*) FROM scrap_loads WHERE truck_ref = %s", (truck,)) == 1


def test_load_key_is_scoped_per_actor(client, material):
    key = new_key()
    body = {"truck_ref": u("TRK-"), "material_code": material}
    a = client.post("/api/loads", json=body, headers=hdr(actor="alice", key=key))
    b = client.post("/api/loads", json=body, headers=hdr(actor="bob", key=key))
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["load_id"] != b.json()["load_id"]


def test_unkeyed_load_create_is_not_deduplicated(client, db, material):
    truck = u("TRK-")
    body = {"truck_ref": truck, "material_code": material}
    assert client.post("/api/loads", json=body, headers=OWNER).status_code == 201
    assert client.post("/api/loads", json=body, headers=OWNER).status_code == 201
    assert count(db, "SELECT count(*) FROM scrap_loads WHERE truck_ref = %s", (truck,)) == 2


def test_malformed_idempotency_key_is_400(client, material):
    r = client.post("/api/loads", json={"material_code": material}, headers=hdr(key="short"))
    assert r.status_code == 400
    assert "Idempotency-Key" in r.json()["detail"]


# -- weighing ----------------------------------------------------------------

def test_second_weigh_is_refused_by_default(client, db, material):
    load_id = make_load(client, material)
    ok = client.post("/api/weigh", json={"load_id": load_id, "gross": 100.0, "tare": 10.0}, headers=OWNER)
    assert ok.status_code == 201
    again = client.post("/api/weigh", json={"load_id": load_id, "gross": 120.0, "tare": 10.0}, headers=OWNER)
    assert again.status_code == 409
    assert "allow_reweigh" in again.json()["detail"]
    assert count(db, "SELECT count(*) FROM scrap_weigh_tickets WHERE load_id = %s", (load_id,)) == 1


def test_reweigh_needs_explicit_flag_and_reason(client, material):
    load_id = make_load(client, material)
    assert client.post("/api/weigh", json={"load_id": load_id, "gross": 100.0, "tare": 10.0}, headers=OWNER).status_code == 201
    no_reason = client.post("/api/weigh", json={"load_id": load_id, "gross": 80.0, "tare": 10.0, "allow_reweigh": True}, headers=OWNER)
    assert no_reason.status_code == 400
    blank_reason = client.post("/api/weigh", json={"load_id": load_id, "gross": 80.0, "tare": 10.0,
                                                   "allow_reweigh": True, "supersede_reason": "   "}, headers=OWNER)
    assert blank_reason.status_code == 400


def test_reweigh_supersedes_earlier_ticket_and_keeps_it(client, material):
    load_id = make_load(client, material)
    first = client.post("/api/weigh", json={"load_id": load_id, "gross": 100.0, "tare": 10.0}, headers=OWNER).json()
    second = client.post("/api/weigh", json={"load_id": load_id, "gross": 80.0, "tare": 10.0, "allow_reweigh": True,
                                             "supersede_reason": "scale re-zeroed"}, headers=OWNER)
    assert second.status_code == 201
    assert second.json()["superseded_ticket_ids"] == [first["ticket_id"]]
    tickets = client.get("/api/loads/%s/weigh-tickets" % load_id, headers=OWNER).json()["tickets"]
    active = [t for t in tickets if t["active"]]
    superseded = [t for t in tickets if not t["active"]]
    assert [t["id"] for t in active] == [second.json()["ticket_id"]]
    assert [t["id"] for t in superseded] == [first["ticket_id"]]
    assert superseded[0]["supersede_reason"] == "scale re-zeroed"


def test_weigh_retry_with_same_key_does_not_double_post(client, db, material):
    load_id = make_load(client, material)
    key = new_key()
    body = {"load_id": load_id, "gross": 100.0, "tare": 10.0}
    first = client.post("/api/weigh", json=body, headers=hdr(key=key))
    again = client.post("/api/weigh", json=body, headers=hdr(key=key))
    assert first.status_code == 201
    assert again.status_code == 200 and again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["ticket_id"] == first.json()["ticket_id"]
    assert count(db, "SELECT count(*) FROM scrap_weigh_tickets WHERE load_id = %s", (load_id,)) == 1


def test_weigh_on_unknown_load_is_404(client):
    r = client.post("/api/weigh", json={"load_id": "LOAD-NOPE0000", "gross": 10.0, "tare": 1.0}, headers=OWNER)
    assert r.status_code == 404


# -- stock movements ---------------------------------------------------------

def test_movement_retry_with_same_key_posts_once(client, material, warehouse):
    key = new_key()
    body = {"material_code": material, "warehouse_code": warehouse, "movement_type": "receipt",
            "quantity": 10.0, "unit": "kg"}
    first = client.post("/api/stock/movements", json=body, headers=hdr(key=key))
    again = client.post("/api/stock/movements", json=body, headers=hdr(key=key))
    assert first.status_code == 201
    assert again.status_code == 200 and again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["movement_id"] == first.json()["movement_id"]
    assert again.json()["new_balance"] == 10.0
    bal = client.get("/api/stock/balance", params={"material_code": material, "warehouse_code": warehouse}, headers=OWNER)
    assert bal.json()["balance"] == 10.0


def test_movement_replay_is_not_blocked_by_later_stock_drop(client, material, warehouse):
    """A retried issue must replay even after stock has been drawn down, not fail as negative."""
    receipt = {"material_code": material, "warehouse_code": warehouse, "movement_type": "receipt", "quantity": 10.0}
    assert client.post("/api/stock/movements", json=receipt, headers=OWNER).status_code == 201
    key = new_key()
    issue = {"material_code": material, "warehouse_code": warehouse, "movement_type": "issue", "quantity": 10.0}
    assert client.post("/api/stock/movements", json=issue, headers=hdr(key=key)).status_code == 201
    replay = client.post("/api/stock/movements", json=issue, headers=hdr(key=key))
    assert replay.status_code == 200
    assert replay.json()["new_balance"] == 0.0


def test_movement_same_key_different_body_is_refused(client, material, warehouse):
    key = new_key()
    base = {"material_code": material, "warehouse_code": warehouse, "movement_type": "receipt", "quantity": 5.0}
    assert client.post("/api/stock/movements", json=base, headers=hdr(key=key)).status_code == 201
    other = dict(base, quantity=6.0)
    assert client.post("/api/stock/movements", json=other, headers=hdr(key=key)).status_code == 409


def test_issue_beyond_balance_is_refused(client, material, warehouse):
    assert client.post("/api/stock/movements", json={"material_code": material, "warehouse_code": warehouse,
                       "movement_type": "receipt", "quantity": 4.0}, headers=OWNER).status_code == 201
    r = client.post("/api/stock/movements", json={"material_code": material, "warehouse_code": warehouse,
                    "movement_type": "issue", "quantity": 4.5}, headers=OWNER)
    assert r.status_code == 409


def test_correction_is_a_corrective_adjustment_and_needs_a_reason(client, material, warehouse):
    client.post("/api/stock/movements", json={"material_code": material, "warehouse_code": warehouse,
                "movement_type": "receipt", "quantity": 10.0}, headers=OWNER)
    no_reason = client.post("/api/stock/movements", json={"material_code": material, "warehouse_code": warehouse,
                            "movement_type": "adjustment", "quantity": -2.0}, headers=OWNER)
    assert no_reason.status_code == 400
    fixed = client.post("/api/stock/movements", json={"material_code": material, "warehouse_code": warehouse,
                        "movement_type": "adjustment", "quantity": -2.0, "reason": "physical count 8"}, headers=OWNER)
    assert fixed.status_code == 201
    assert fixed.json()["new_balance"] == 8.0


def test_no_update_or_delete_route_exists_for_movements(client, material, warehouse):
    posted = client.post("/api/stock/movements", json={"material_code": material, "warehouse_code": warehouse,
                         "movement_type": "receipt", "quantity": 3.0}, headers=OWNER).json()
    path = "/api/stock/movements/%d" % posted["movement_id"]
    for method in ("PATCH", "PUT", "DELETE"):
        r = client.request(method, path, json={"quantity": 0}, headers=OWNER)
        assert r.status_code in (404, 405), (method, r.status_code)
    bal = client.get("/api/stock/balance", params={"material_code": material, "warehouse_code": warehouse}, headers=OWNER)
    assert bal.json()["balance"] == 3.0


def test_trace_includes_movements_beyond_list_limit(client, db, material, warehouse):
    load_id = make_load(client, material)
    # The load's movement is the oldest; 250 newer unrelated movements would push it out of a 200-row list.
    db.execute(
        """INSERT INTO scrap_stock_movements (material_code, warehouse_code, movement_type, quantity, unit, reference, actor, reason, created_at)
           VALUES (%s,%s,'receipt',7,'kg',%s,'ops',NULL, now() - interval '1 day')""",
        (material, warehouse, load_id),
    )
    db.execute(
        """INSERT INTO scrap_stock_movements (material_code, warehouse_code, movement_type, quantity, unit, reference, actor, reason)
           SELECT %s, %s, 'receipt', 1, 'kg', 'filler', 'ops', NULL FROM generate_series(1, 250)""",
        (material, warehouse),
    )
    trace = client.get("/api/trace/%s" % load_id, headers=OWNER).json()
    assert [m["quantity"] for m in trace["stock_movements"]] == [7.0]


# -- sales: orders and deliveries -------------------------------------------

def test_order_retry_with_same_key_does_not_duplicate_items(client, db, material):
    key = new_key()
    body = {"currency": "EUR", "items": [{"material_code": material, "quantity": 5.0, "price_per_unit": 2.0}]}
    first = client.post("/api/orders", json=body, headers=hdr(key=key))
    again = client.post("/api/orders", json=body, headers=hdr(key=key))
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json()["order_number"] == first.json()["order_number"]
    assert len(again.json()["items"]) == 1
    assert count(db, "SELECT count(*) FROM scrap_orders WHERE order_number = %s", (first.json()["order_number"],)) == 1


def test_delivery_retry_with_same_key_returns_same_delivery(client, material):
    order = client.post("/api/orders", json={"currency": "EUR",
                        "items": [{"material_code": material, "quantity": 1.0, "price_per_unit": 1.0}]},
                        headers=OWNER).json()
    key = new_key()
    body = {"order_number": order["order_number"]}
    first = client.post("/api/deliveries", json=body, headers=hdr(key=key))
    again = client.post("/api/deliveries", json=body, headers=hdr(key=key))
    assert first.status_code == 201
    assert again.status_code == 200
    assert again.json()["delivery_id"] == first.json()["delivery_id"]


def test_confirming_delivery_twice_is_rejected_and_keeps_first_confirmation(client, material):
    order = client.post("/api/orders", json={"currency": "EUR",
                        "items": [{"material_code": material, "quantity": 1.0, "price_per_unit": 1.0}]},
                        headers=OWNER).json()
    did = client.post("/api/deliveries", json={"order_number": order["order_number"]}, headers=OWNER).json()["delivery_id"]
    first = client.post("/api/deliveries/%d/confirm" % did, json={"delivered_by": "driver1"}, headers=OWNER)
    assert first.status_code == 200
    assert first.json()["status"] == "delivered"
    second = client.post("/api/deliveries/%d/confirm" % did, json={"delivered_by": "driver2"}, headers=OWNER)
    assert second.status_code == 409
    delivery = client.get("/api/orders/%s" % order["order_number"], headers=OWNER).json()["deliveries"][0]
    assert delivery["delivered_by"] == "driver1"


def test_confirm_unknown_delivery_is_404(client):
    r = client.post("/api/deliveries/999999999/confirm", json={"delivered_by": "driver1"}, headers=OWNER)
    assert r.status_code == 404


def test_delivery_for_unknown_load_is_404(client, material):
    order = client.post("/api/orders", json={"currency": "EUR",
                        "items": [{"material_code": material, "quantity": 1.0, "price_per_unit": 1.0}]},
                        headers=OWNER).json()
    r = client.post("/api/deliveries", json={"order_number": order["order_number"], "load_id": "LOAD-NOPE0000"}, headers=OWNER)
    assert r.status_code == 404


# -- roles -------------------------------------------------------------------

WRITE_CALLS = [
    ("post", "/api/materials", {"code": "RV", "name": "x", "category": "metal"}),
    ("post", "/api/warehouses", {"code": "RV", "name": "x"}),
    ("post", "/api/loads", {"truck_ref": "T"}),
    ("post", "/api/loads/LOAD-NOPE0000/status?status=weighed", None),
    ("post", "/api/weigh", {"load_id": "LOAD-NOPE0000", "gross": 10.0, "tare": 1.0}),
    ("post", "/api/stock/movements", {"material_code": "M", "warehouse_code": "W", "movement_type": "receipt", "quantity": 1.0}),
    ("post", "/api/customers", {"code": "RV", "name": "x"}),
    ("post", "/api/orders", {"items": []}),
    ("post", "/api/orders/ORD-NOPE0000/status?status=x", None),
    ("post", "/api/deliveries", {"order_number": "ORD-NOPE0000"}),
    ("post", "/api/deliveries/1/confirm", {"delivered_by": "d"}),
]


@pytest.mark.parametrize("method,path,body", WRITE_CALLS)
@pytest.mark.parametrize("role", ["viewer", "admin", "", "superuser"])
def test_read_only_or_unknown_roles_cannot_write(client, method, path, body, role):
    r = getattr(client, method)(path, json=body, headers=hdr(role=role))
    assert r.status_code == 403, (path, role, r.status_code, r.text)


@pytest.mark.parametrize("role", ["owner", "fleet_manager", "warehouse_operator", " Owner "])
def test_writer_roles_can_write(client, role):
    code = u("RW")
    r = client.post("/api/materials", json={"code": code, "name": "x", "category": "metal"}, headers=hdr(role=role))
    assert r.status_code == 201


def test_viewer_can_still_read(client, material):
    assert client.get("/api/materials", headers=hdr(role="viewer")).status_code == 200
    assert client.get("/api/stock/movements", headers=hdr(role="viewer")).status_code == 200


def test_token_is_required_when_anonymous_is_off(db):
    s = Settings(api_token="t" * 32, database_url=DATABASE_URL)
    app = create_app(settings=s, db=db)
    with TestClient(app) as c:
        assert c.get("/api/meta", headers={"X-Actor": "ops", "X-Actor-Role": "owner"}).status_code == 401
        assert c.get("/api/meta", headers={"X-Actor": "ops", "X-Actor-Role": "owner", "X-Service-Token": "wrong"}).status_code == 401
        ok = c.get("/api/meta", headers={"X-Actor": "ops", "X-Actor-Role": "owner", "X-Service-Token": "t" * 32})
        assert ok.status_code == 200
        bearer = c.post("/api/materials", json={"code": u("RB"), "name": "x", "category": "metal"},
                        headers={"X-Actor": "ops", "X-Actor-Role": "owner", "Authorization": "Bearer " + "t" * 32})
        assert bearer.status_code == 201
        no_actor = c.post("/api/materials", json={"code": u("RB"), "name": "x", "category": "metal"},
                          headers={"X-Service-Token": "t" * 32, "X-Actor-Role": "owner"})
        assert no_actor.status_code == 401
