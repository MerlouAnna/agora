from services.data_service.categories import Warehouse
from services.data_service.delivery import Store
from services.offer_service import scenario_builder as builder
from services.offer_service.domain.models import Availability, Risk, Strategy
from services.offer_service.requirements import Constraint, CustomerRequirements

SUPPLIERS = {
    "SUP-01": {"code": "SUP-01", "lead_time_days": 3, "reliability_score": 0.96},
    "SUP-03": {"code": "SUP-03", "lead_time_days": 14, "reliability_score": 0.74},
}


def ups(sku: str, autonomy: int, price: float, held: list[tuple[str, int]], supplier="SUP-01"):
    return {
        "sku": sku,
        "category": "UPS",
        "brand": "Voltera",
        "description": f"UPS {autonomy} λεπτά",
        "price": price,
        "supplier_code": supplier,
        "specs": {"va": 1500, "autonomy_min": autonomy},
        "warehouses": [{"warehouse": w, "quantity": q} for w, q in held],
    }


def asked(**changes) -> CustomerRequirements:
    return CustomerRequirements(request="δοκιμή", category="UPS", **changes)


def only(products, requirements, store=Store.ATHENS, before_cut_off=True):
    """One candidate, so the strategies all land on it and the scenario is its own."""
    return builder.build(requirements, products, SUPPLIERS, store, before_cut_off)[0]


def test_a_quantity_no_single_warehouse_covers_is_drawn_from_two():
    """The one combination this builder makes, because quantities are what actually add up.

    Thessaloniki is the case that decides the order: its serving warehouse holds the
    smaller half, so drawing from the fullest first would put the other one in front.
    """
    split = ups("UPS-B", 35, 640.0, [("ATH-01", 8), ("THE-01", 4)])

    far = only([split], asked(quantity=12), store=Store.TRIPOLI)
    served = only([split], asked(quantity=12), store=Store.THESSALONIKI)

    assert [(source.warehouse, source.quantity) for source in far.lines[0].sources] == [
        (Warehouse.ATH_01, 8),
        (Warehouse.THE_01, 4),
    ]
    assert [(source.warehouse, source.quantity) for source in served.lines[0].sources] == [
        (Warehouse.THE_01, 4),
        (Warehouse.ATH_01, 8),
    ]
    assert far.availability == Availability.TRANSFER
    assert far.days == 3
    assert far.transfer_cost == 15.0


def test_a_product_the_warehouse_system_never_heard_of_gets_no_date():
    """Reading that silence as an empty shelf would turn a gap in the data into a promise."""
    unrecorded = ups("UPS-D", 20, 295.0, [], supplier="SUP-03")

    found = only([unrecorded], asked(quantity=5))

    assert found.availability == Availability.UNKNOWN
    assert found.days is None
    assert found.risk == Risk.MEDIUM
    assert any("not the same as none" in note for note in found.notes)


def test_same_day_is_narrower_than_being_in_stock():
    """Άμεση παράδοση is Attica, out of ATH-01 or ATH-02, before 13:00, and nothing else."""
    here = ups("UPS-A", 20, 320.0, [("ATH-01", 40)])

    assert only([here], asked(quantity=5)).days == 0
    assert only([here], asked(quantity=5), before_cut_off=False).days == 1
    assert only([here], asked(quantity=5), store=Store.THESSALONIKI).days == 2
    assert only([here], asked(quantity=5)).availability == Availability.SAME_DAY


def test_a_product_with_more_than_was_asked_for_loses_to_one_that_matches():
    """Both satisfy the floor: the closer one is the match, the dearer one is the step up."""
    close = ups("UPS-A", 20, 320.0, [("ATH-01", 40)])
    over = ups("UPS-C", 35, 1380.0, [("ATH-01", 40)])
    wanted = asked(quantity=5, constraints=[Constraint(key="autonomy_min", op="gte", value=20)])

    built = builder.build(wanted, [close, over], SUPPLIERS, Store.ATHENS)
    picked = {
        strategy: scenario.lines[0].sku
        for scenario in built
        for strategy in scenario.strategies
    }

    assert picked[Strategy.BEST_TECHNICAL] == "UPS-A"
    assert picked[Strategy.PREMIUM] == "UPS-C"


def test_one_product_that_answers_several_criteria_is_offered_once():
    """Five labels over two products would be three of them saying the same thing twice."""
    close = ups("UPS-A", 20, 320.0, [("ATH-01", 40)])
    over = ups("UPS-C", 35, 1380.0, [("ATH-01", 40)])
    wanted = asked(quantity=5, constraints=[Constraint(key="autonomy_min", op="gte", value=20)])

    built = builder.build(wanted, [close, over], SUPPLIERS, Store.ATHENS)

    assert [scenario.lines[0].sku for scenario in built] == ["UPS-A", "UPS-C"]
    assert Strategy.CHEAPEST in built[0].strategies
    assert Strategy.BEST_TECHNICAL in built[0].strategies


def test_an_urgent_order_on_a_supplier_that_will_not_commit_is_flagged_high():
    """The delivery terms refuse the promise below 0.80, and only for an urgent order."""
    scarce = ups("UPS-D", 20, 295.0, [("ATH-01", 2)], supplier="SUP-03")

    urgent = only([scarce], asked(quantity=10, immediate=True))
    ordinary = only([scarce], asked(quantity=10))

    assert urgent.risk == Risk.HIGH
    assert any("urgent" in note for note in urgent.notes)
    assert ordinary.risk == Risk.MEDIUM
    assert urgent.days == ordinary.days == 16
