"""Pure weight logic tests."""

from scrap.domain.weights import WeighTicket, compute_net, WeightError, convert_to_kg


def test_net_basic():
    assert compute_net(100.0, 30.0) == 70.0


def test_net_rounding():
    assert compute_net(100.1234, 30.0) == 70.123


def test_tare_exceeds_gross_raises():
    try:
        compute_net(10.0, 20.0)
        assert False, "expected error"
    except WeightError:
        pass


def test_negative_gross_raises():
    try:
        compute_net(-5.0, 1.0)
        assert False
    except WeightError:
        pass


def test_zero_both_raises():
    try:
        compute_net(0.0, 0.0)
        assert False
    except WeightError:
        pass


def test_implausible_net_raises():
    try:
        compute_net(60000.0, 1.0)
        assert False
    except WeightError:
        pass


def test_validate_returns_problems():
    t = WeighTicket(gross=5.0, tare=10.0)
    assert t.validate()


def test_is_plausible():
    t = WeighTicket(gross=50.0, tare=10.0)
    assert t.is_plausible()


def test_convert_to_kg():
    assert convert_to_kg(1.0, "t") == 1000.0
    assert abs(convert_to_kg(1.0, "lb") - 0.45359237) < 1e-9
    assert convert_to_kg(5.0, "kg") == 5.0


def test_unit_validation():
    t = WeighTicket(gross=10.0, tare=2.0, unit="oz")
    assert "unit must be" in " ".join(t.validate())
