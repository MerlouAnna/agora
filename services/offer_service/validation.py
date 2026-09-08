"""
Offer validation
================
The last gate before a scenario reaches a customer: every figure it carries, worked out
again from the catalogue as it stands right now, rather than taken on trust. What this
catches is a builder that miscounted and a warehouse row that has moved since the offer
was priced. What it cannot catch is a misreading of the business documents, because it
reads the same registries the builder does — that is what the scenario eval is for.

A scenario the customer would be misled by is withheld. Every other finding travels with
the offer, because a salesperson who is told is better off than one who is not.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from services.data_service import discounts
from services.data_service.categories import Warehouse
from services.data_service.delivery import (
    Store,
    Zone,
    shipping,
    transfer_cost,
    working_days,
    zone_of,
)
from services.offer_service.clients import catalog
from services.offer_service.domain.models import Allocation, OfferLine, OfferScenario
from services.offer_service.requirements import CustomerRequirements

logger = logging.getLogger(__name__)

CENT = 0.011


class Severity(StrEnum):
    """Whether a failure withholds the offer or travels with it."""

    FATAL = "fatal"
    WARNING = "warning"


@dataclass(frozen=True)
class Check:
    """One question asked of one scenario, and the answer."""

    name: str
    severity: Severity
    passed: bool
    said: str = ""


@dataclass(frozen=True)
class Verdict:
    """Everything asked of one scenario, in the order a reader would ask it."""

    scenario: OfferScenario
    checks: list[Check]

    @property
    def failed(self) -> list[Check]:
        return [check for check in self.checks if not check.passed]

    @property
    def offerable(self) -> bool:
        return not any(
            check.severity == Severity.FATAL for check in self.checks if not check.passed
        )


@dataclass(frozen=True)
class ValidationReport:
    """Every scenario that was built, and which of them may be shown."""

    verdicts: list[Verdict]

    @property
    def offers(self) -> list[OfferScenario]:
        return [verdict.scenario for verdict in self.verdicts if verdict.offerable]

    @property
    def withheld(self) -> list[Verdict]:
        return [verdict for verdict in self.verdicts if not verdict.offerable]

    @property
    def failed(self) -> list[Check]:
        return [check for verdict in self.verdicts for check in verdict.failed]


def validate(
    scenarios: list[OfferScenario],
    requirements: CustomerRequirements,
    store: Store,
    catalogue: Callable[[list[str]], list[dict]] | None = None,
    registry: Callable[[], list[dict]] | None = None,
    before_cut_off: bool = True,
) -> ValidationReport:
    """Ask every scenario what it is claiming, and check the catalogue agrees.

    Args:
        scenarios: What the builder produced.
        requirements: What was asked for, which is what the budget and condition checks read.
        store: The branch the order was raised from, which fixes the destination zone.
        catalogue: What reads the products again. Replaced in tests and in the tools.
        registry: What reads the suppliers, needed to date a quantity being ordered in.
        before_cut_off: Whether the order is confirmed by 13:00, as when it was priced.

    Returns:
        One verdict per scenario, in the order they were built.
    """
    wanted = sorted({line.sku for scenario in scenarios for line in scenario.lines})
    if not wanted:
        return ValidationReport(verdicts=[])

    held = {str(row["sku"]): row for row in (catalogue or catalog.lookup)(wanted)}
    leads = {
        str(row["code"]): row.get("lead_time_days") for row in (registry or catalog.suppliers)()
    }

    zone = zone_of(store)
    verdicts = [_verdict(one, held, leads, requirements, zone, before_cut_off) for one in scenarios]

    withheld = [verdict for verdict in verdicts if not verdict.offerable]
    if withheld:
        logger.warning("%d of %d scenarios are withheld", len(withheld), len(verdicts))

    return ValidationReport(verdicts=verdicts)


def _verdict(
    scenario: OfferScenario,
    held: dict,
    leads: dict,
    requirements: CustomerRequirements,
    zone: Zone,
    before_cut_off: bool,
) -> Verdict:
    checks = []
    for line in scenario.lines:
        checks += _line(line, held.get(line.sku))

    if any(line.sku not in held for line in scenario.lines):
        return Verdict(scenario=scenario, checks=checks)

    row = held[scenario.lines[0].sku]
    checks += _money(scenario, row, zone)
    checks += _promise(scenario, row, leads, zone, before_cut_off)
    checks += _request(scenario, row, requirements)

    return Verdict(scenario=scenario, checks=checks)


def _line(line: OfferLine, row: dict | None) -> list[Check]:
    """What the catalogue says about the product this line is selling."""
    if row is None:
        return [
            Check(
                "the sku is in the catalogue",
                Severity.FATAL,
                False,
                f"{line.sku} is not a product the catalogue holds",
            )
        ]

    listed = row.get("price")
    stock = {
        str(entry["warehouse"]): int(entry["quantity"]) for entry in row.get("warehouses") or []
    }
    strange = [
        source.warehouse.value
        for source in line.sources
        if source.warehouse is not None and source.warehouse.value not in stock
    ]
    short = [
        f"{source.warehouse.value} is asked for {source.quantity} and holds "
        f"{stock.get(source.warehouse.value, 0)}"
        for source in line.sources
        if source.warehouse is not None and source.quantity > stock.get(source.warehouse.value, 0)
    ]

    return [
        Check("the sku is in the catalogue", Severity.FATAL, True),
        Check(
            "the unit price is the catalogue's",
            Severity.FATAL,
            listed is not None and abs(float(listed) - line.unit_price) < CENT,
            f"the line says {line.unit_price} and the catalogue says {listed}",
        ),
        Check(
            "every warehouse named holds this product",
            Severity.FATAL,
            not strange,
            f"no record of {line.sku} in {', '.join(strange)}",
        ),
        Check(
            "no warehouse is asked for more than it holds",
            Severity.FATAL,
            not short,
            "; ".join(short),
        ),
    ]


def _money(scenario: OfferScenario, row: dict, zone: Zone) -> list[Check]:
    """Every figure between the line totals and what the customer pays."""
    net = scenario.net
    earned = discounts.rate(net, row["category"])
    moved = max(transfer_cost(zone, _from(source)) for source in _sources(scenario))

    return [
        Check(
            "the discount is the band this order earns, held down by its category",
            Severity.FATAL,
            abs(earned - scenario.discount_rate) < 1e-9,
            f"the offer gives {scenario.discount_rate:.0%} where {earned:.0%} is earned",
        ),
        Check(
            "the discount in euro follows the rate",
            Severity.FATAL,
            abs(net * scenario.discount_rate - scenario.discount) < CENT,
            f"{scenario.discount_rate:.0%} of {net} is not {scenario.discount}",
        ),
        Check(
            "the carriage is the destination's, waived above the threshold",
            Severity.FATAL,
            abs(shipping(zone, net) - scenario.shipping) < CENT,
            f"the offer charges {scenario.shipping} where {shipping(zone, net)} applies",
        ),
        Check(
            "the internal transfer is charged when the stock has to move",
            Severity.FATAL,
            abs(moved - scenario.transfer_cost) < CENT,
            f"the offer records {scenario.transfer_cost} where {moved} applies",
        ),
        Check(
            "the total is the net less the discount plus the carriage",
            Severity.FATAL,
            abs(net - scenario.discount + scenario.shipping - scenario.total) < CENT,
            f"{net} − {scenario.discount} + {scenario.shipping} is not {scenario.total}",
        ),
    ]


def _promise(
    scenario: OfferScenario, row: dict, leads: dict, zone: Zone, before_cut_off: bool
) -> list[Check]:
    """The date and the approval, which are promises rather than prices."""
    lead = leads.get(str(row.get("supplier_code") or ""))
    sources = _sources(scenario)
    datable = lead is not None or all(source.warehouse is not None for source in sources)

    dated = None
    if datable and scenario.days is not None:
        dated = max(
            working_days(zone, _from(source), lead_time=lead, before_cut_off=before_cut_off)
            for source in sources
        )

    return [
        Check(
            "the promised date is what the delivery terms give",
            Severity.FATAL,
            dated is None or dated == scenario.days,
            f"the offer promises {scenario.days} working days where the terms give {dated}",
        ),
        Check(
            "approval is read on the band this order's value earns",
            Severity.FATAL,
            discounts.needs_approval(scenario.net) == scenario.needs_approval,
            f"the offer says {scenario.needs_approval} for an order of {scenario.net}",
        ),
        Check(
            "the discount is the salesperson's own to sign",
            Severity.WARNING,
            not scenario.needs_approval,
            "the sales manager has to approve the band before this goes out",
        ),
    ]


def _request(scenario: OfferScenario, row: dict, requirements: CustomerRequirements) -> list[Check]:
    """Whether the offer answers what was actually asked for."""
    specs = row.get("specs") or {}
    unmet = [
        f"{constraint.key} {constraint.op} {constraint.value}"
        for constraint in requirements.constraints
        if specs.get(constraint.key) is None or not constraint.holds(specs[constraint.key])
    ]
    unit = scenario.lines[0].unit_price
    offered = sum(line.quantity for line in scenario.lines)
    ordered = requirements.quantity or 1

    return [
        Check(
            "the quantity offered is the quantity asked for",
            Severity.FATAL,
            offered == ordered,
            f"the offer is for {offered} where {ordered} were asked for",
        ),
        Check(
            "the product meets every condition the request named",
            Severity.WARNING,
            not unmet,
            "does not meet " + ", ".join(unmet),
        ),
        Check(
            "the unit price is inside the budget per unit",
            Severity.WARNING,
            requirements.price_max is None or unit <= requirements.price_max + CENT,
            f"{unit} a unit against a budget of {requirements.price_max}",
        ),
        Check(
            "the order is inside the budget for the whole of it",
            Severity.WARNING,
            requirements.budget_max is None or scenario.total <= requirements.budget_max + CENT,
            f"{scenario.total} against a budget of {requirements.budget_max}",
        ),
    ]


def _sources(scenario: OfferScenario) -> list[Allocation]:
    return [source for line in scenario.lines for source in line.sources]


def _from(source: Allocation) -> Warehouse | None:
    return source.warehouse
