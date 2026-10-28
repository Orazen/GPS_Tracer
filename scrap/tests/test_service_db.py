"""Database-backed scrap service tests.

Skipped unless SCRAP_TEST_DATABASE_URL is set.
"""

import os
import pytest

from fastapi.testclient import TestClient

from scrap.config import load_settings
from scrap.api.app import create_app

DATABASE_URL = os.environ.get("SCRAP_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="SCRAP_TEST_DATABASE_URL is not set")


@pytest.fixture(scope="module")
def client():
    s = load_settings(allow_anonymous=True)
    s.database_url = DATABASE_URL
    app = create_app(settings=s)
    with TestClient(app) as c:
        yield c


def test_healthz(client):
    assert client.get("/healthz").text == "ok"


import uuid as _uuid

def test_load_weigh_stock_flow(client):
    code = "CU" + _uuid.uuid4().hex[:6].upper()
    wh = "WH" + _uuid.uuid4().hex[:6].upper()
    client.post("/api/materials", json={"code": code, "name": "Copper", "category": "metal", "unit": "kg"},
                headers={"X-Actor": "admin", "X-Actor-Role": "owner"})
    client.post("/api/warehouses", json={"code": wh, "name": "Main"}, headers={"X-Actor": "admin", "X-Actor-Role": "owner"})
    r = client.post("/api/loads", json={"truck_ref": "T1", "material_code": code},
                    headers={"X-Actor": "admin", "X-Actor-Role": "owner"})
    assert r.status_code == 201
    load_id = r.json()["load_id"]
    r = client.post("/api/weigh", json={"load_id": load_id, "gross": 100.0, "tare": 12.5, "unit": "kg"},
                    headers={"X-Actor": "admin", "X-Actor-Role": "owner"})
    assert r.status_code == 201
    assert r.json()["net"] == 87.5
    r = client.post("/api/stock/movements", json={"material_code": code, "warehouse_code": wh,
                    "movement_type": "receipt", "quantity": 87.5, "unit": "kg", "reference": load_id},
                    headers={"X-Actor": "admin", "X-Actor-Role": "owner"})
    assert r.status_code == 201
    r = client.get("/api/stock/balance", params={"material_code": code, "warehouse_code": wh},
                   headers={"X-Actor": "admin", "X-Actor-Role": "owner"})
    assert r.json()["balance"] == 87.5
    # negative stock prevention
    r = client.post("/api/stock/movements", json={"material_code": code, "warehouse_code": wh,
                    "movement_type": "issue", "quantity": 1000.0, "unit": "kg"},
                    headers={"X-Actor": "admin", "X-Actor-Role": "owner"})
    assert r.status_code == 409


def test_viewer_cannot_write(client):
    r = client.post("/api/materials", json={"code": "BR", "name": "Brass", "category": "metal"},
                    headers={"X-Actor": "viewer", "X-Actor-Role": "viewer"})
    assert r.status_code == 403
