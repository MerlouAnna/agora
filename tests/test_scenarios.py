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


def switch(sku: str, poe: str, price: float):
    return {
        "sku": sku,
        "category": "NETWORK",
        "brand": "Voltera",
        "description": f"Switch 24 θυρών PoE={poe}",
        "price": price,
        "supplier_code": "SUP-01",
        "specs": {"ports": 24, "poe": poe, "managed": "true"},
        "warehouses": [{"warehouse": "ATH-01", "quantity": 40}],
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
    """Reading that silence as an empty shelf would turn a gap in the data into a promise.

    A shelf the registry cannot name a supplier for is the other way round: the stock is
    there, so the date is too.
    """
    unrecorded = ups("UPS-D", 20, 295.0, [], supplier="SUP-03")
    stranger = ups("UPS-E", 20, 295.0, [("ATH-01", 40)], supplier="SUP-99")

    found = only([unrecorded], asked(quantity=5))
    held = only([stranger], asked(quantity=5))

    assert found.availability == Availability.UNKNOWN
    assert found.days is None
    assert found.risk == Risk.MEDIUM
    assert any("not the same as none" in note for note in found.notes)
    assert held.availability == Availability.SAME_DAY
    assert held.days == 0


def test_same_day_is_narrower_than_being_in_stock():
    """Άμεση παράδοση is Attica, out of ATH-01 or ATH-02, before 13:00, and nothing else."""
    here = ups("UPS-A", 20, 320.0, [("ATH-01", 40)])

    assert only([here], asked(quantity=5)).days == 0
    assert only([here], asked(quantity=5), before_cut_off=False).days == 1
    assert only([here], asked(quantity=5), store=Store.THESSALONIKI).days == 3
    assert only([here], asked(quantity=5)).availability == Availability.SAME_DAY


def test_a_product_with_more_than_was_asked_for_loses_to_one_that_matches():
    """Both satisfy the floor: the closer one is the match, the dearer one is the step up.

    On a graded label the floor moves with the comparison: under `gt CAT6` the nearest
    grade that qualifies is CAT6a, and the nearest grade costs nothing.
    """
    close = ups("UPS-A", 20, 320.0, [("ATH-01", 40)])
    over = ups("UPS-C", 35, 1380.0, [("ATH-01", 40)])
    wanted = asked(quantity=5, constraints=[Constraint(key="autonomy_min", op="gte", value=20)])

    built = builder.build(wanted, [close, over], SUPPLIERS, Store.ATHENS)
    picked = {
        strategy: scenario.lines[0].sku for scenario in built for strategy in scenario.strategies
    }

    assert picked[Strategy.BEST_TECHNICAL] == "UPS-A"
    assert picked[Strategy.PREMIUM] == "UPS-C"
    assert builder._overshoot(Constraint(key="standard", op="gt", value="CAT6"), "CAT6a", 0.0) == 0
    assert builder._overshoot(Constraint(key="standard", op="gt", value="CAT6"), "CAT7", 0.0) == 1
    assert builder._overshoot(Constraint(key="standard", op="gte", value="CAT6"), "CAT6", 0.0) == 0


def test_one_product_that_answers_several_criteria_is_offered_once():
    """Five labels over two products would be three of them saying the same thing twice."""
    close = ups("UPS-A", 20, 320.0, [("ATH-01", 40)])
    over = ups("UPS-C", 35, 1380.0, [("ATH-01", 40)])
    wanted = asked(quantity=5, constraints=[Constraint(key="autonomy_min", op="gte", value=20)])

    built = builder.build(wanted, [close, over], SUPPLIERS, Store.ATHENS)

    assert [scenario.lines[0].sku for scenario in built] == ["UPS-A", "UPS-C"]
    assert Strategy.CHEAPEST in built[0].strategies
    assert Strategy.BEST_TECHNICAL in built[0].strategies

    table = builder.compare(built)
    assert [row["skus"] for row in table] == [["UPS-A"], ["UPS-C"]]
    assert table[0]["strategies"] == [strategy.value for strategy in built[0].strategies]
    assert table[0]["quantity"] == 5
    assert table[0]["total"] == built[0].total
    assert [row["discount"] for row in table] == [48.0, 345.0]


def test_a_flag_the_catalogue_stores_as_text_is_read_as_a_flag():
    """The catalogue writes `poe` as the text "true" or "false", and every string is truthy."""
    without = switch("SWT-A", "false", 210.0)
    with_poe = switch("SWT-B", "true", 340.0)
    wanted = CustomerRequirements(
        request="switch με PoE",
        category="NETWORK",
        quantity=2,
        constraints=[Constraint(key="poe", op="eq", value=True)],
    )

    refused = builder.build(wanted, [without], SUPPLIERS, Store.ATHENS)[0]
    accepted = builder.build(wanted, [with_poe], SUPPLIERS, Store.ATHENS)[0]

    assert refused.fit == 0.0
    assert any("does not meet poe" in note for note in refused.notes)
    assert accepted.fit == 1.0


def test_the_budget_moves_the_most_for_the_money_off_a_unit_nobody_can_afford():
    """`price_max` is read here and nowhere else in `services/`, so nothing else guards it."""
    over = ups("UPS-C", 35, 320.0, [("ATH-01", 40)])
    exact = ups("UPS-A", 20, 400.0, [("ATH-01", 40)])
    floor = [Constraint(key="autonomy_min", op="gte", value=20)]

    unbounded = builder.build(
        asked(quantity=5, constraints=floor), [over, exact], SUPPLIERS, Store.ATHENS
    )
    bounded = builder.build(
        asked(quantity=5, price_max=350.0, constraints=floor),
        [over, exact],
        SUPPLIERS,
        Store.ATHENS,
    )

    assert _chose(unbounded, Strategy.BEST_BUDGET) == "UPS-A"
    assert _chose(bounded, Strategy.BEST_BUDGET) == "UPS-C"


def test_a_product_the_catalogue_holds_no_price_for_is_not_offered_at_nothing():
    """Zero is a number, and as a unit price it reads as the cheapest offer on the table."""
    unpriced = ups("UPS-F", 20, None, [("ATH-01", 40)])
    priced = ups("UPS-A", 20, 320.0, [("ATH-01", 40)])

    built = builder.build(asked(quantity=5), [unpriced, priced], SUPPLIERS, Store.ATHENS)

    assert [scenario.lines[0].sku for scenario in built] == ["UPS-A"]
    assert builder.build(asked(quantity=5), [unpriced], SUPPLIERS, Store.ATHENS) == []


def test_an_urgent_order_on_a_supplier_that_will_not_commit_is_flagged_high():
    """The delivery terms refuse the promise below 0.80, and only for an urgent order."""
    scarce = ups("UPS-D", 20, 295.0, [("ATH-01", 2)], supplier="SUP-03")
    stranger = ups("UPS-E", 20, 295.0, [("ATH-01", 2)], supplier="SUP-99")

    urgent = only([scarce], asked(quantity=10, immediate=True))
    ordinary = only([scarce], asked(quantity=10))
    unknown = only([stranger], asked(quantity=10, immediate=True))

    assert urgent.risk == Risk.HIGH
    assert any("urgent" in note for note in urgent.notes)
    assert ordinary.risk == Risk.MEDIUM
    assert urgent.days == ordinary.days == 16
    assert unknown.risk == Risk.HIGH


def test_a_condition_on_an_offer_carries_the_figure_it_rests_on():
    """A note that names a condition without its number sends the reader to the policy.

    Attica serves the islands, so the move that costs two days is the one out of Patra.
    """
    attica = ups("UPS-A", 20, 320.0, [("ATH-01", 40)])
    patra = ups("UPS-B", 20, 320.0, [("PAT-01", 40)])

    same_day = only([attica], asked(quantity=5))
    moved = only([attica], asked(quantity=5), store=Store.THESSALONIKI)
    island = only([patra], asked(quantity=5), store=Store.HERAKLION)

    assert any("13:00" in note for note in same_day.notes)
    assert any("adds 1 working day" in note for note in moved.notes)
    assert any("adds 2 working days" in note for note in island.notes)


def _chose(built, strategy) -> str:
    return next(scenario.lines[0].sku for scenario in built if strategy in scenario.strategies)
