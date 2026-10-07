import pytest

from vigil_pipeline.units import allowed_units, normalise_unit, numbers_in, parse_number


@pytest.mark.parametrize("raw,expected", [
    ("mAh", ("Ah", 0.001)), ("Ah", ("Ah", 1.0)), ("V", ("V", 1.0)), ("mV", ("V", 0.001)),
    ("A", ("A", 1.0)), ("mA", ("A", 0.001)), ("Wh", ("Wh", 1.0)), ("kWh", ("Wh", 1000.0)),
    ("mΩ", ("mΩ", 1.0)), ("mohm", ("mΩ", 1.0)), ("Ω", ("mΩ", 1000.0)), ("g", ("g", 1.0)),
    ("kg", ("g", 1000.0)), ("%", ("%", 1.0)), ("°C", ("°C", 1.0)), ("℃", ("°C", 1.0)),
    ("degC", ("°C", 1.0)), ("oC", ("°C", 1.0)), ("deg.C", ("°C", 1.0)), ("cycles", ("cycles", 1.0)), (" m A h ", ("Ah", 0.001)),
])
def test_normalise_unit(raw, expected):
    assert normalise_unit(raw) == expected


def test_normalise_unit_unknown():
    assert normalise_unit("furlongs") is None
    assert normalise_unit("") is None


def test_allowed_units():
    assert allowed_units("Ah") == ["Ah", "mAh"]
    assert allowed_units("mΩ") == ["mΩ", "Ω"]
    assert allowed_units("kg CO2e/kWh") == []


def test_numbers_in_handles_commas_and_ranges():
    assert numbers_in("3,500 mAh") == [3500.0]
    assert numbers_in("3,6 V") == [3.6]
    assert numbers_in("2.5-4.2V") == [2.5, 4.2]
    assert numbers_in("−20 ~ 60 °C") == [-20.0, 60.0]
    assert numbers_in("-20°C to 60°C") == [-20.0, 60.0]
    assert numbers_in("1 000 cycles") == [1000.0]
    assert numbers_in("no numbers") == []


def test_parse_number():
    assert parse_number("3500") == 3500.0
    assert parse_number("approx. 3.635") == 3.635
    assert parse_number("n/a") is None
