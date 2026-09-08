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
    promises_urgent,
    shipping,
    transfer_cost,
    working_days,
    zone_of,
)
from services.offer_service.clients import catalog
from services.offer_service.domain.models import (
    Allocation,
    Availability,
    OfferLine,
    OfferScenario,
    Risk,
    availability_of,
)
from services.offer_service.requirements import CustomerRequirements

logger = logging.getLogger(__name__)

# A figure that differs only by a rounding, one meant to be the same number, and `fit`,
# which the builder rounds to four places.
CENT = 0.011
EXACT = 1e-9
FIT = 1e-4


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
        registry: What reads the suppliers, needed to date and to rate a quantity ordered in.
        before_cut_off: Whether the order is confirmed by 13:00, as when it was priced.

    Returns:
        One verdict per scenario, in the order they were built.
    """
    wanted = sorted({line.sku for scenario in scenarios for line in scenario.lines})
    if not wanted:
        return ValidationReport(verdicts=[])

    held = {str(row["sku"]): row for row in (catalogue or catalog.lookup)(wanted)}
    known = {str(row["code"]): row for row in (registry or catalog.suppliers)()}

    zone = zone_of(store)
    verdicts = [_verdict(one, held, known, requirements, zone, before_cut_off) for one in scenarios]

    withheld = [verdict for verdict in verdicts if not verdict.offerable]
    if withheld:
        logger.warning("%d of %d scenarios are withheld", len(withheld), len(verdicts))

    return ValidationReport(verdicts=verdicts)


def _verdict(
    scenario: OfferScenario,
    held: dict,
    known: dict,
    requirements: CustomerRequirements,
    zone: Zone,
    before_cut_off: bool,
) -> Verdict:
    if not scenario.lines:
        return Verdict(
            scenario=scenario,
            checks=[
                Check(
                    "the offer has something to sell",
                    Severity.FATAL,
                    False,
                    "the scenario carries no lines",
                )
            ],
        )

    checks = []
    for line in scenario.lines:
        checks += _line(line, held.get(line.sku))

    if any(line.sku not in held for line in scenario.lines):
        return Verdict(scenario=scenario, checks=checks)

    row = held[scenario.lines[0].sku]
    supplier = known.get(str(row.get("supplier_code") or ""), {})
    checks += _money(scenario, row, zone)
    checks += _promise(scenario, row, supplier, requirements, zone, before_cut_off)
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
    # What a warehouse holds covers every allocation drawn on it, not one at a time.
    wanted: dict[str, int] = {}
    for source in line.sources:
        if source.warehouse is not None:
            wanted[source.warehouse.value] = wanted.get(source.warehouse.value, 0) + source.quantity

    strange = [name for name in wanted if name not in stock]
    short = [
        f"{name} is asked for {asked} and holds {stock.get(name, 0)}"
        for name, asked in wanted.items()
        if asked > stock.get(name, 0)
    ]
    sourced = sum(source.quantity for source in line.sources)

    return [
        Check("the sku is in the catalogue", Severity.FATAL, True),
        Check(
            "the unit price is the catalogue's",
            Severity.FATAL,
            listed is not None and abs(float(listed) - line.unit_price) < EXACT,
            f"the line says {line.unit_price} and the catalogue says {listed}",
        ),
        Check(
            "the description is the catalogue's",
            Severity.WARNING,
            line.description == row.get("description"),
            f"the line reads {line.description!r} where the catalogue reads "
            f"{row.get('description')!r}",
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
        Check(
            "the allocations add up to the quantity the line sells",
            Severity.FATAL,
            sourced == line.quantity,
            f"{line.quantity} are offered and {sourced} are sourced",
        ),
    ]


def _money(scenario: OfferScenario, row: dict, zone: Zone) -> list[Check]:
    """Every figure between the line totals and what the customer pays."""
    net = scenario.net
    earned = discounts.rate(net, row["category"])
    carriage = shipping(zone, net)
    moved = max([transfer_cost(zone, _from(source)) for source in _sources(scenario)], default=0.0)

    return [
        Check(
            "the discount is the band this order earns, held down by its category",
            Severity.FATAL,
            abs(earned - scenario.discount_rate) < EXACT,
            f"the offer gives {scenario.discount_rate:.0%} where {earned:.0%} is earned",
        ),
        Check(
            "the discount in euro follows the band",
            Severity.FATAL,
            abs(net * earned - scenario.discount) < CENT,
            f"{earned:.0%} of {net} is not {scenario.discount}",
        ),
        Check(
            "the carriage is the destination's, waived above the threshold",
            Severity.FATAL,
            abs(carriage - scenario.shipping) < CENT,
            f"the offer charges {scenario.shipping} where {carriage} applies",
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
            abs(net - net * earned + carriage - scenario.total) < CENT,
            f"{net} − {net * earned:.2f} + {carriage} is not {scenario.total}",
        ),
    ]


def _promise(
    scenario: OfferScenario,
    row: dict,
    supplier: dict,
    requirements: CustomerRequirements,
    zone: Zone,
    before_cut_off: bool,
) -> list[Check]:
    """The date, the risk and the approval, which are promises rather than prices."""
    lead = supplier.get("lead_time_days")
    sources = _sources(scenario)
    told = (
        availability_of(sources, zone, before_cut_off)
        if row.get("warehouses")
        else Availability.UNKNOWN
    )
    datable = (
        bool(sources)
        and told is not Availability.UNKNOWN
        and (lead is not None or all(source.warehouse is not None for source in sources))
    )

    borne = _risk(told, supplier, requirements)
    dated = None
    if datable:
        dated = max(
            working_days(zone, _from(source), lead_time=lead, before_cut_off=before_cut_off)
            for source in sources
        )

    return [
        Check(
            "what the offer calls the stock is what the allocation amounts to",
            Severity.FATAL,
            told == scenario.availability,
            f"the offer says {scenario.availability.value} where the allocation is {told.value}",
        ),
        Check(
            "the promised date is what the delivery terms give",
            Severity.FATAL,
            not datable or dated == scenario.days,
            f"the offer promises {scenario.days} working days where the terms give {dated}",
        ),
        Check(
            "the risk is what the allocation and the supplier make of it",
            Severity.WARNING,
            borne == scenario.risk,
            f"the offer calls this {scenario.risk.value} where the allocation makes it "
            f"{borne.value}",
        ),
        Check(
            "the discount is the salesperson's own to sign",
            Severity.WARNING,
            not scenario.needs_approval,
            "the sales manager has to approve the band before this goes out",
        ),
    ]


def _risk(told: Availability, supplier: dict, requirements: CustomerRequirements) -> Risk:
    """What the promise rests on beyond a warehouse shelf, read off the allocation."""
    if told == Availability.ORDERED:
        reliability = supplier.get("reliability_score")
        committed = reliability is not None and promises_urgent(float(reliability))
        return Risk.HIGH if requirements.immediate and not committed else Risk.MEDIUM

    return Risk.MEDIUM if told == Availability.UNKNOWN else Risk.LOW


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
    allowed, exact = _allowance(requirements, unmet)

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
        Check(
            "the fit is what the conditions it meets allow",
            Severity.WARNING,
            abs(scenario.fit - allowed) < FIT if exact else scenario.fit <= allowed + FIT,
            f"the offer scores {scenario.fit} where the conditions it meets allow "
            f"{round(allowed, 4)}",
        ),
    ]


def _allowance(requirements: CustomerRequirements, unmet: list[str]) -> tuple[float, bool]:
    """The most `fit` a product missing these conditions can score, and whether it is the figure.

    A miss costs a whole share and overshoot part of one, and only a floor overshoots.
    """
    if not requirements.constraints:
        return 1.0, True

    floors = any(constraint.op in ("gte", "gt") for constraint in requirements.constraints)
    return 1.0 - len(unmet) / len(requirements.constraints), not floors


def _sources(scenario: OfferScenario) -> list[Allocation]:
    return [source for line in scenario.lines for source in line.sources]


def _from(source: Allocation) -> Warehouse | None:
    return source.warehouse
