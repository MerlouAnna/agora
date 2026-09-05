import pytest

from services.data_service.categories import Category
from services.data_service.ingestion import parsers


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("PWR-1007", "PWR-1007"),
        ("pwr1007", "PWR-1007"),
        ("PWR 1003", "PWR-1003"),
        ('"PWR-1007"', "PWR-1007"),
        ("", None),
    ],
)
def test_normalize_sku(raw, expected):
    assert parsers.normalize_sku(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("€ 134,20", 134.20), ("163.95", 163.95), ("145,17 EUR", 145.17), ("N/A", None)],
)
def test_parse_price(raw, expected):
    assert parsers.parse_price(raw) == expected


def test_parse_quantity_rejects_a_dash():
    assert parsers.parse_quantity("42") == 42
    assert parsers.parse_quantity("-") is None


@pytest.mark.parametrize("raw, expected", [("20m", 20), ("20 μ.", 20), ("2000cm", 20)])
def test_parse_length_m(raw, expected):
    assert (
        parsers.parse_length_m(f"Καλώδιο ρεύματος 3x1.5mm {raw} 1000W IP44") == expected
    )


def test_section_is_not_read_as_a_length():
    """3x2.5mm must not leak into length_m as 5 metres."""
    assert parsers.parse_length_m("Καλώδιο ρεύματος 3x2.5mm 30m 2200W IP54") == 30


def test_parse_watt_converts_kilowatts():
    assert parsers.parse_watt("Καλώδιο ρεύματος 3x2.5mm 20m 3kW IP44") == 3000


def test_extract_specs():
    power = "Καλώδιο ρεύματος 5x6.0mm 25 μ. 1500W IP67 εξωτερικού χώρου"
    assert parsers.extract_specs(Category.POWER, power) == {
        "cores": 5,
        "section_mm": 6.0,
        "length_m": 25,
        "watt": 1500,
        "ip_rating": "IP67",
    }

    ups = "UPS line-interactive 1500VA / 900W αυτονομία 20 λεπτά"
    assert parsers.extract_specs(Category.UPS, ups)["va"] == 1500
    assert parsers.extract_specs(Category.UPS, ups)["watt"] == 900


def test_unmanaged_is_not_read_as_managed():
    specs = parsers.extract_specs(
        Category.NETWORK, "Switch 48 θυρών 2500Mbps PoE unmanaged"
    )
    assert (specs["poe"], specs["managed"]) == (True, False)
