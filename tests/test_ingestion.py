import pytest

from services.data_service.ingestion import loader, normalizer

SUPPLIERS = {"SUP-01"}


def record(**changes) -> dict:
    return {
        "sku": "PWR-1000",
        "category": "POWER",
        "brand": "Elektra",
        "description": "Καλώδιο ρεύματος 3x2.5mm 20m 1500W IP44 εξωτερικού χώρου",
        "unit": "ΤΕΜ",
        "supplier": "SUP-01",
        "price": 134.20,
        "currency": "EUR",
        "stock": [{"warehouse": "ATH-01", "quantity": 40}],
        **changes,
    }


def test_a_record_with_no_description_is_a_rejection_not_a_crash():
    products, _, rejections = normalizer.normalize_catalog(
        [record(description=None), record(sku="PWR-1001")], SUPPLIERS
    )

    assert [p.sku for p in products] == ["PWR-1001"]
    assert len(rejections) == 1


def test_the_same_warehouse_twice_becomes_one_row():
    """The stock table holds one row per SKU and warehouse, so the second line is the same line."""
    entry = {"warehouse": "ATH-01", "quantity": 40}
    _, stock, _ = normalizer.normalize_catalog([record(stock=[entry, entry])], SUPPLIERS)

    assert len(stock) == 1


@pytest.mark.parametrize("price", ["N/A", 0, -12.5])
def test_a_price_that_cannot_be_used_costs_the_price_not_the_product(price):
    products, stock, rejections = normalizer.normalize_catalog(
        [record(price=price)], SUPPLIERS
    )

    assert [p.sku for p in products] == ["PWR-1000"]
    assert products[0].price is None
    assert len(stock) == 1
    assert rejections[0].reason in ("unreadable price", "price not above zero")


def test_a_supplier_the_registry_never_heard_of_is_refused():
    products, _, rejections = normalizer.normalize_catalog(
        [record(supplier="SUP-99")], SUPPLIERS
    )

    assert products[0].supplier_code is None
    assert rejections[0].reason == "unknown supplier"


def test_something_that_is_not_a_csv_is_refused_as_text():
    with pytest.raises(ValueError):
        loader.read_upload(b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + bytes(range(256)) * 8)
