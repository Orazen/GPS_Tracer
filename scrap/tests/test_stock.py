"""Pure stock ledger tests."""

from scrap.domain.stock import Movement, compute_balance, would_go_negative, VALID_MOVEMENT_TYPES


def test_receipt_positive():
    m = Movement(material_id=1, warehouse_id=1, quantity=10, movement_type="receipt")
    assert m.signed_quantity() == 10


def test_issue_negative():
    m = Movement(material_id=1, warehouse_id=1, quantity=5, movement_type="issue")
    assert m.signed_quantity() == -5


def test_reservation_negative():
    m = Movement(material_id=1, warehouse_id=1, quantity=3, movement_type="reservation")
    assert m.signed_quantity() == -3


def test_compute_balance():
    ms = [
        Movement(material_id=1, warehouse_id=1, quantity=100, movement_type="receipt"),
        Movement(material_id=1, warehouse_id=1, quantity=30, movement_type="issue"),
        Movement(material_id=1, warehouse_id=1, quantity=5, movement_type="adjustment"),
    ]
    assert compute_balance(ms) == 75.0


def test_would_go_negative_true():
    m = Movement(material_id=1, warehouse_id=1, quantity=10, movement_type="issue")
    assert would_go_negative(5.0, m) is True


def test_would_go_negative_false():
    m = Movement(material_id=1, warehouse_id=1, quantity=3, movement_type="issue")
    assert would_go_negative(5.0, m) is False


def test_would_go_negative_allowed():
    m = Movement(material_id=1, warehouse_id=1, quantity=10, movement_type="issue")
    assert would_go_negative(5.0, m, allow_negative=True) is False


def test_validate_unknown_type():
    m = Movement(material_id=1, warehouse_id=1, quantity=1, movement_type="foo")
    assert m.validate()


def test_validate_zero_quantity():
    m = Movement(material_id=1, warehouse_id=1, quantity=0, movement_type="receipt")
    assert m.validate()


def test_valid_types_set():
    assert "receipt" in VALID_MOVEMENT_TYPES
    assert "adjustment" in VALID_MOVEMENT_TYPES
