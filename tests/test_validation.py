from dataclasses import replace

import pytest

from services.data_service.categories import Warehouse
from services.data_service.delivery import Store
from services.offer_service import scenario_builder as builder
from services.offer_service import validation
from services.offer_service.domain.models import Risk
from services.offer_service.requirements import Constraint, CustomerRequirements
from services.offer_service.validation import Severity

SUPPLIERS = {"SUP-01": {"code": "SUP-01", "lead_time_days": 3, "reliability_score": 0.96}}
REGISTRY = [{"code": "SUP-01", "lead_time_days": 3, "reliability_score": 0.96}]

ROW = {
    "sku": "UPS-A",
    "category": "UPS",
    "brand": "Voltera",
    "description": "UPS 20 λεπτά",
    "price": 320.0,
    "supplier_code": "SUP-01",
    "specs": {"va": 1500, "autonomy_min": 20},
    "warehouses": [{"warehouse": "ATH-01", "quantity": 40}],
}


def asked(**changes) -> CustomerRequirements:
    return CustomerRequirements(request="δοκιμή", category="UPS", quantity=5, **changes)


def offer(requirements=None):
    """One scenario over one product, priced from the same row the validator reads back."""
    return builder.build(requirements or asked(), [ROW], SUPPLIERS, Store.ATHENS)[0]


def report(scenarios, requirements=None, rows=None):
    return validation.validate(
        scenarios,
        requirements or asked(),
        Store.ATHENS,
        catalogue=lambda skus: [
            row for row in ([ROW] if rows is None else rows) if row["sku"] in skus
        ],
        registry=lambda: REGISTRY,
    )


def test_an_offer_the_catalogue_agrees_with_passes_every_check():
    """The happy path has to be silent, or nothing below it means anything."""
    verdict = report([offer()]).verdicts[0]

    assert verdict.failed == []
    assert verdict.offerable
    assert len(verdict.checks) == 20


@pytest.mark.parametrize(
    ("corruption", "caught", "severity"),
    [
        ({"lines": "price"}, ("the unit price is the catalogue's",), Severity.FATAL),
        ({"lines": "cent"}, ("the unit price is the catalogue's",), Severity.FATAL),
        (
            {"lines": "quantity"},
            (
                "the quantity offered is the quantity asked for",
                "the allocations add up to the quantity the line sells",
            ),
            Severity.FATAL,
        ),
        (
            {"lines": "elsewhere"},
            (
                "every warehouse named holds this product",
                "no warehouse is asked for more than it holds",
                "the internal transfer is charged when the stock has to move",
                "what the offer calls the stock is what the allocation amounts to",
                "the promised date is what the delivery terms give",
            ),
            Severity.FATAL,
        ),
        (
            {"lines": "greedy"},
            (
                "no warehouse is asked for more than it holds",
                "the allocations add up to the quantity the line sells",
            ),
            Severity.FATAL,
        ),
        (
            {"lines": "short"},
            ("the allocations add up to the quantity the line sells",),
            Severity.FATAL,
        ),
        (
            {"discount_rate": 0.05},
            (
                "the discount is the band this order earns, held down by its category",
                "the discount in euro follows the band",
                "the total is the net less the discount plus the carriage",
            ),
            Severity.FATAL,
        ),
        (
            {"shipping": 9.0},
            (
                "the carriage is the destination's, waived above the threshold",
                "the total is the net less the discount plus the carriage",
            ),
            Severity.FATAL,
        ),
        (
            {"transfer_cost": 15.0},
            ("the internal transfer is charged when the stock has to move",),
            Severity.FATAL,
        ),
        ({"days": 4}, ("the promised date is what the delivery terms give",), Severity.FATAL),
        ({"days": None}, ("the promised date is what the delivery terms give",), Severity.FATAL),
        ({"lines": "renamed"}, ("the description is the catalogue's",), Severity.WARNING),
        (
            {"risk": Risk.HIGH},
            ("the risk is what the allocation and the supplier make of it",),
            Severity.WARNING,
        ),
        ({"fit": 0.5}, ("the fit is what the conditions it meets allow",), Severity.WARNING),
    ],
)
def test_every_corruption_is_caught_by_the_checks_that_own_it(corruption, caught, severity):
    """A table, because the point is the mapping and not any single case.

    Moving the stock to a warehouse that never held it breaks five claims at once — where
    it is, whether it is there, what the move costs, what the stock is called and when it
    lands — so the expected failures are written out rather than assumed to be one. A cent
    is its own row: it is real money and no rounding produces it.
    """
    broken = _corrupt(offer(), corruption)

    failed = report([broken]).failed

    assert {one.name for one in failed} == set(caught)
    assert all(one.severity == severity and one.said for one in failed)


def test_a_scenario_that_fails_a_fatal_check_is_withheld_and_the_others_still_go_out():
    """A wrong number never reaches a customer, and it does not take the good offers with it."""
    good, bad = offer(), _corrupt(offer(), {"lines": "price"})

    checked = report([good, bad])

    assert checked.offers == [good]
    assert [verdict.scenario for verdict in checked.withheld] == [bad]


def test_a_condition_the_offer_misses_travels_with_it_instead_of_withholding_it():
    """The builder answers an impossible request with the nearest thing; that is not a defect."""
    wanted = asked(constraints=[Constraint(key="autonomy_min", op="gte", value=35)])

    verdict = report([offer(wanted)], wanted).verdicts[0]

    assert [one.name for one in verdict.failed] == [
        "the product meets every condition the request named"
    ]
    assert verdict.failed[0].severity == Severity.WARNING
    assert verdict.offerable


def test_the_budget_for_one_unit_and_the_budget_for_the_order_are_read_apart():
    """320 € a unit is inside 350 a unit and outside 1.000 for five of them."""
    per_unit = asked(price_max=350.0)
    tight = asked(price_max=300.0)
    whole = asked(budget_max=1000.0)

    assert report([offer()], per_unit).failed == []
    assert [one.name for one in report([offer()], tight).failed] == [
        "the unit price is inside the budget per unit"
    ]
    assert [one.name for one in report([offer()], whole).failed] == [
        "the order is inside the budget for the whole of it"
    ]


def test_a_sku_the_catalogue_no_longer_holds_stops_the_checks_that_rest_on_it():
    """Reporting a wrong price for a product that does not exist would be noise, not a finding."""
    verdict = report([offer()], rows=[]).verdicts[0]

    assert [one.name for one in verdict.failed] == ["the sku is in the catalogue"]
    assert len(verdict.checks) == 1
    assert not verdict.offerable


def test_a_scenario_with_nothing_behind_it_is_refused_rather_than_raised():
    """`validate` is the public gate, so a malformed scenario has to come back as a verdict."""
    empty = replace(offer(), lines=[])
    unsourced = _corrupt(offer(), {"lines": "unsourced"})

    checked = report([empty, unsourced, offer()])

    assert [one.name for one in checked.failed] == [
        "the offer has something to sell",
        "the allocations add up to the quantity the line sells",
    ]
    assert len(checked.offers) == 1


def _corrupt(scenario, how: dict):
    """Bend one figure of a built offer, the way a bug or a stale row would."""
    if "lines" not in how:
        return replace(scenario, **how)

    line = scenario.lines[0]
    if how["lines"] == "price":
        line = replace(line, unit_price=line.unit_price + 10.0)
    elif how["lines"] == "cent":
        line = replace(line, unit_price=line.unit_price + 0.01)
    elif how["lines"] == "quantity":
        line = replace(line, quantity=line.quantity + 1)
    elif how["lines"] == "renamed":
        line = replace(line, description="UPS 20 λεπτών")
    elif how["lines"] == "elsewhere":
        line = replace(line, sources=[replace(line.sources[0], warehouse=Warehouse.PAT_01)])
    elif how["lines"] == "unsourced":
        line = replace(line, sources=[])
    elif how["lines"] == "short":
        line = replace(line, sources=[replace(line.sources[0], quantity=line.quantity - 2)])
    else:
        line = replace(line, sources=[replace(line.sources[0], quantity=400)])

    return replace(scenario, lines=[line])
