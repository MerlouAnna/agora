import pytest

from services.data_service.categories import NUMERIC, SPEC_TYPES
from services.offer_service.rag import documents


def product(sku="PWR-1042", category="POWER", **specs):
    return {
        "sku": sku,
        "category": category,
        "brand": "Delta Line",
        "description": "Καλώδιο ρεύματος 5x1.5mm 1500cm 3kW IP54",
        "web_description": "Πενταπολικό καλώδιο για εργοτάξιο.",
        "supplier_code": "SUP-04",
        "specs": specs,
    }


def test_every_numeric_spec_can_be_written_out():
    numeric = {key for key, kind in SPEC_TYPES.items() if kind == NUMERIC}
    assert numeric <= set(documents.UNITS)


def test_the_card_carries_its_own_code():
    card = documents.build_cards([product(watt=3000)])[0]
    assert "PWR-1042" in card.text


def test_a_switch_without_poe_never_says_poe():
    off, on = documents.build_cards(
        [
            product(sku="SWT-1000", category="NETWORK", ports=24, poe="false", managed="true"),
            product(sku="SWT-1001", category="NETWORK", ports=24, poe="true", managed="true"),
        ]
    )
    assert "PoE" not in off.text
    assert "PoE" in on.text
    assert off.metadata["poe"] is False


def test_a_card_reads_the_same_whatever_else_the_catalogue_holds():
    """The card is a function of one product: nothing about its neighbours reaches it."""
    alone = documents.build_cards([product(cores=5, length_m=50)])[0]
    crowded = documents.build_cards(
        [product(cores=5, length_m=50)]
        + [product(sku=f"PWR-10{n:02d}", cores=3, length_m=5) for n in range(1, 9)]
    )[0]

    assert alone.text == crowded.text


@pytest.mark.parametrize("field", ["price", "stock_total", "currency"])
def test_what_changes_without_a_reindex_is_never_indexed(field):
    record = product(watt=3000) | {"price": 96.2, "stock_total": 40, "currency": "EUR"}
    assert field not in documents.metadata_for(record)


def test_specs_reach_the_metadata_as_numbers():
    metadata = documents.metadata_for(product(watt=3000, section_mm=1.5, ip_rating="IP54"))
    assert metadata["watt"] == 3000
    assert metadata["section_mm"] == 1.5
    assert metadata["ip_rating"] == "IP54"
