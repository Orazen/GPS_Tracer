"""Pure tests for idempotency-key handling and the adjustment-reason rule."""

import pytest

from scrap.domain.idempotency import IdempotencyKeyError, normalise_key, request_hash, scoped_key
from scrap.domain.stock import Movement


def test_missing_or_blank_key_means_no_idempotency():
    assert normalise_key(None) is None
    assert normalise_key("   ") is None


def test_valid_key_is_stripped_and_kept():
    assert normalise_key("  load-20261028-abc123  ") == "load-20261028-abc123"


@pytest.mark.parametrize("bad", ["short", "has space in it", "x" * 129, "semi;colon-key", "emoji-🙂-key"])
def test_invalid_keys_are_refused(bad):
    with pytest.raises(IdempotencyKeyError):
        normalise_key(bad)


def test_scope_separates_routes_and_actors():
    key = "same-key-value"
    assert scoped_key("loads.create", "alice", key) != scoped_key("loads.create", "bob", key)
    assert scoped_key("loads.create", "alice", key) != scoped_key("weigh.create", "alice", key)


def test_request_hash_ignores_dict_order_but_not_values():
    a = request_hash({"quantity": 10.0, "material_code": "CU"})
    b = request_hash({"material_code": "CU", "quantity": 10.0})
    c = request_hash({"material_code": "CU", "quantity": 10.5})
    assert a == b
    assert a != c


def test_adjustment_requires_a_reason():
    m = Movement(material_id=0, warehouse_id=0, quantity=-3, movement_type="adjustment")
    assert any("reason" in p for p in m.validate())


def test_adjustment_with_reason_is_valid():
    m = Movement(material_id=0, warehouse_id=0, quantity=-3, movement_type="adjustment", reason="count correction")
    assert m.validate() == []
