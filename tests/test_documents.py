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


def test_every_numeric_spec_can_be_written_and_compared():
    numeric = {key for key, kind in SPEC_TYPES.items() if kind == NUMERIC}
    assert numeric <= set(documents.EXTREMES)
    assert numeric <= set(documents.UNITS)


def test_the_card_carries_its_own_code():
    card = documents.build_cards([product(watt=3000)])[0]
    assert "PWR-1042" in card.text


def test_a_switch_without_poe_never_says_poe():
    off, on = (
        documents.build_cards(
            [
                product(sku="SWT-1000", category="NETWORK", ports=24, poe="false", managed="true"),
                product(sku="SWT-1001", category="NETWORK", ports=24, poe="true", managed="true"),
            ]
        )
    )
    assert "PoE" not in off.text
    assert "PoE" in on.text
    assert off.metadata["poe"] is False


def test_a_flag_is_named_when_it_is_rare_and_never_named_when_it_is_off():
    """A switch without PoE is not the one switch in ten that has it."""
    mostly_on = {"poe": ["true"] * 9 + ["false"]}
    mostly_off = {"poe": ["false"] * 9 + ["true"]}

    assert documents.context_line({"poe": "false"}, mostly_on) == documents.MID_RANGE
    assert "σπάνιο PoE" in documents.context_line({"poe": "true"}, mostly_off)


def test_an_extreme_most_of_the_category_shares_is_not_worth_saying():
    """Three cores is the lowest we sell and also what two thirds of the shelf holds."""
    cohort = {"cores": [3] * 8 + [5] * 4}
    assert documents.context_line({"cores": 3}, cohort) == documents.MID_RANGE
    assert "οι περισσότεροι αγωγοί" in documents.context_line({"cores": 5}, cohort)


def test_a_product_that_stands_out_nowhere_gets_no_context_line():
    plain, longest = documents.build_cards(
        [
            product(sku="DAT-1000", category="DATA", standard="CAT6", length_m=5),
            product(sku="DAT-1001", category="DATA", standard="CAT6", length_m=30),
        ]
        + [
            product(sku=f"DAT-10{n:02d}", category="DATA", standard="CAT6", length_m=5)
            for n in range(2, 8)
        ]
    )[:2]
    assert documents.CONTEXT_PREFIX not in plain.text
    assert "το μεγαλύτερο μήκος" in longest.text


@pytest.mark.parametrize("field", ["price", "stock_total", "currency"])
def test_what_changes_without_a_reindex_is_never_indexed(field):
    record = product(watt=3000) | {"price": 96.2, "stock_total": 40, "currency": "EUR"}
    assert field not in documents.metadata_for(record)


def test_specs_reach_the_metadata_as_numbers():
    metadata = documents.metadata_for(product(watt=3000, section_mm=1.5, ip_rating="IP54"))
    assert metadata["watt"] == 3000
    assert metadata["section_mm"] == 1.5
    assert metadata["ip_rating"] == "IP54"
