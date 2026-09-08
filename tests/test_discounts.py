from services.data_service.categories import Category
from services.data_service.delivery import Store
from services.data_service.discounts import cap, needs_approval, rate, volume_rate
from services.offer_service import scenario_builder as builder
from services.offer_service.domain.models import Strategy
from services.offer_service.requirements import CustomerRequirements

SUPPLIERS = {"SUP-01": {"code": "SUP-01", "lead_time_days": 3, "reliability_score": 0.96}}


def ups(sku: str, price: float):
    return {
        "sku": sku,
        "category": "UPS",
        "brand": "Voltera",
        "description": f"UPS {sku}",
        "price": price,
        "supplier_code": "SUP-01",
        "specs": {"va": 2200},
        "warehouses": [{"warehouse": "ATH-01", "quantity": 40}],
    }


def test_a_band_starts_at_its_own_figure_and_two_bands_never_add_up():
    """The policy prints «Παραγγελία 800 € παίρνει 3%», so 799,99 € is still the band below."""
    assert volume_rate(799.99) == 0.0
    assert volume_rate(800.0) == 0.03
    assert volume_rate(4000.0) == 0.05
    assert volume_rate(15000.0) == 0.08


def test_the_category_ceiling_erases_the_band_above_it():
    """The same 8.139,92 € order earns 7%, and a UPS line is still given 5%."""
    assert volume_rate(8139.92) == 0.07
    assert rate(8139.92, Category.DATA) == 0.07
    assert rate(8139.92, Category.UPS) == cap(Category.UPS) == 0.05


def test_approval_is_read_on_the_band_and_not_on_what_the_ceiling_let_through():
    """Two orders given the same 5%: the one whose band is 7% is not the salesperson's.

    And the note the offer carries says so, because a 5% discount is one the salesperson
    signs off alone — it is the order's band that needs the manager.
    """
    assert rate(8139.92, Category.UPS) == rate(4000.0, Category.PSU) == 0.05
    assert needs_approval(8139.92)
    assert not needs_approval(4000.0)
    assert not needs_approval(7999.99)
    assert needs_approval(8000.0)

    asked = CustomerRequirements(request="δοκιμή", category="UPS", quantity=8)
    over = builder.build(asked, [ups("UPS-OVER", 1017.49)], SUPPLIERS, Store.ATHENS)[0]
    under = builder.build(asked, [ups("UPS-UNDER", 500.0)], SUPPLIERS, Store.ATHENS)[0]

    assert (over.net, over.discount_rate, over.needs_approval) == (8139.92, 0.05, True)
    assert any("band needs the sales manager" in note for note in over.notes)
    assert (under.net, under.discount_rate, under.needs_approval) == (4000.0, 0.05, False)
    assert not any("sales manager" in note for note in under.notes)
    assert [row["needs_approval"] for row in builder.compare([over, under])] == [True, False]


def test_the_volume_band_can_make_the_dearer_product_the_cheaper_order():
    """A band is read on the order's value, so 810 € of goods can cost less than 799 €."""
    asked = CustomerRequirements(request="δοκιμή", category="UPS", quantity=1)
    candidates = [ups("UPS-UNDER", 799.0), ups("UPS-OVER", 810.0)]

    built = builder.build(asked, candidates, SUPPLIERS, Store.ATHENS)
    cheapest = next(one for one in built if Strategy.CHEAPEST in one.strategies)

    assert cheapest.lines[0].sku == "UPS-OVER"
    assert (cheapest.net, cheapest.discount, cheapest.total) == (810.0, 24.3, 785.7)
