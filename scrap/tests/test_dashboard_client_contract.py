"""Contract between dashboard/src/api/scrap.js and the scrap API.

This is a documentation test, not a unit test of the JavaScript. The dashboard has
no JS test runner in this track, so the client itself is untested here. What this
file pins down, without a database or a browser:

* every endpoint the client calls exists with the expected method;
* the client sends Idempotency-Key only to endpoints whose handler reads it;
* the client never mentions the service token or the forwarded identity headers.
"""

import inspect
from pathlib import Path

import pytest

from scrap.api.app import create_app
from scrap.config import load_settings

CLIENT = Path(__file__).resolve().parents[2] / "dashboard" / "src" / "api" / "scrap.js"

# (method, route template, idempotent?, substring the JS must contain)
CONTRACT = [
    ("GET", "/api/meta", False, "'/meta'"),
    ("GET", "/api/materials", False, "'/materials'"),
    ("POST", "/api/materials", False, "write('/materials'"),
    ("GET", "/api/warehouses", False, "'/warehouses'"),
    ("POST", "/api/warehouses", False, "write('/warehouses'"),
    ("GET", "/api/customers", False, "'/customers'"),
    ("POST", "/api/customers", False, "write('/customers'"),
    ("GET", "/api/loads", False, "'/loads'"),
    ("POST", "/api/loads", True, "write('/loads'"),
    ("GET", "/api/loads/{load_id}", False, "`/loads/${enc(loadId)}`"),
    ("POST", "/api/loads/{load_id}/status", False, "/status`"),
    ("POST", "/api/weigh", True, "write('/weigh'"),
    ("GET", "/api/loads/{load_id}/weigh-tickets", False, "/weigh-tickets`"),
    ("GET", "/api/stock/balance", False, "'/stock/balance'"),
    ("GET", "/api/stock/movements", False, "'/stock/movements'"),
    ("POST", "/api/stock/movements", True, "write('/stock/movements'"),
    ("GET", "/api/orders", False, "'/orders'"),
    ("POST", "/api/orders", True, "write('/orders'"),
    ("GET", "/api/orders/{order_number}", False, "`/orders/${enc(orderNumber)}`"),
    ("POST", "/api/deliveries", True, "write('/deliveries'"),
    ("POST", "/api/deliveries/{delivery_id}/confirm", False, "/confirm`"),
    ("GET", "/api/trace/{load_id}", False, "`/trace/${enc(loadId)}`"),
    ("GET", "/api/audit", False, "'/audit'"),
    ("GET", "/api/reports/loads.csv", False, "/reports/loads.csv`"),
]

FORBIDDEN_IN_CLIENT = ["SCRAP_API_TOKEN", "Authorization", "Bearer", "X-Actor", "X-Service-Token", "X-Actor-Role"]


@pytest.fixture(scope="module")
def app():
    return create_app(settings=load_settings(allow_anonymous=True))


@pytest.fixture(scope="module")
def client_js():
    return CLIENT.read_text(encoding="utf-8")


def _route(app, method, template):
    for route in app.routes:
        if getattr(route, "path", None) == template and method in getattr(route, "methods", set()):
            return route
    return None


@pytest.mark.parametrize("method,template,idempotent,fragment", CONTRACT)
def test_client_endpoint_exists_on_service(app, method, template, idempotent, fragment):
    assert _route(app, method, template) is not None, "%s %s is called by scrap.js but not served" % (method, template)


@pytest.mark.parametrize("method,template,idempotent,fragment", CONTRACT)
def test_client_path_literal_present_in_client(client_js, method, template, idempotent, fragment):
    assert fragment in client_js, "scrap.js does not contain %r for %s %s" % (fragment, method, template)


@pytest.mark.parametrize("method,template,idempotent,fragment", CONTRACT)
def test_idempotency_key_only_where_handler_reads_it(app, method, template, idempotent, fragment):
    route = _route(app, method, template)
    reads_key = "idempotency_key" in inspect.signature(route.endpoint).parameters
    assert reads_key is idempotent, (
        "%s %s: handler reads Idempotency-Key=%s but scrap.js marks idempotent=%s"
        % (method, template, reads_key, idempotent)
    )


def test_client_sends_no_credentials_or_forwarded_identity(client_js):
    for token in FORBIDDEN_IN_CLIENT:
        assert token not in client_js, "scrap.js must not reference %r; the dashboard server adds it" % token


def test_client_uses_same_origin_proxy_prefix(client_js):
    assert "const BASE = '/scrap/api'" in client_js
    assert "https://" not in client_js and "http://" not in client_js
