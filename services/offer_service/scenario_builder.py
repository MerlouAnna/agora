"""
Scenario builder
================
The same candidates read five ways: cheapest that works, closest to what was asked, most
for the money, soonest in the customer's hands, and one step up. No model is called and
nothing is fetched — everything here is arithmetic over rows the caller already has.
"""

from dataclasses import dataclass

from services.data_service.categories import ORDERED_LABELS, Warehouse, is_numeric
from services.data_service.delivery import (
    Store,
    Zone,
    promises_urgent,
    same_day,
    serves,
    shipping,
    transfer_cost,
    working_days,
    zone_of,
)
from services.offer_service.domain.models import (
    Allocation,
    Availability,
    OfferLine,
    OfferScenario,
    Risk,
    Strategy,
)
from services.offer_service.requirements import Constraint, CustomerRequirements


@dataclass(frozen=True)
class Priced:
    """One candidate with everything the strategies compare it on."""

    product: dict
    zone: Zone
    fit: float
    missing: list[str]
    lines: list[OfferLine]
    availability: Availability
    days: int | None
    risk: Risk
    transfer: float
    notes: list[str]

    @property
    def net(self) -> float:
        return round(sum(line.line_total for line in self.lines), 2)

    @property
    def total(self) -> float:
        return round(self.net + shipping(self.zone, self.net), 2)


def build(
    requirements: CustomerRequirements,
    products: list[dict],
    suppliers: dict[str, dict],
    store: Store,
    before_cut_off: bool = True,
) -> list[OfferScenario]:
    """Five offers over the same candidates, or fewer when they keep landing on one product.

    Args:
        requirements: What was asked for, as the extractor read it.
        products: Candidate rows as the products API returns them, best first.
        suppliers: The supplier registry, keyed by code.
        store: The branch raising the order, which fixes the destination zone.
        before_cut_off: Whether the order is confirmed by 13:00.

    Returns:
        One scenario per distinct offer, each carrying every strategy that chose it.
    """
    zone = zone_of(store)
    spreads = _spreads(requirements, products)
    quantity = requirements.quantity or 1

    priced = [
        _price(product, requirements, spreads, suppliers, zone, quantity, before_cut_off)
        for product in products
    ]
    whole = [one for one in priced if not one.missing]

    picks: dict[tuple, tuple[Priced, list[Strategy]]] = {}
    for strategy, pick in (
        (Strategy.CHEAPEST, _cheapest),
        (Strategy.BEST_TECHNICAL, _closest),
        (Strategy.BEST_BUDGET, _most_for_the_money),
        (Strategy.BEST_AVAILABILITY, _soonest),
        (Strategy.PREMIUM, _step_up),
    ):
        one = pick(whole or priced, requirements)
        if one is None:
            continue

        mark = _mark(one)
        if mark in picks:
            picks[mark][1].append(strategy)
            continue

        picks[mark] = (one, [strategy])

    return [_scenario(labels, one) for one, labels in picks.values()]


def compare(scenarios: list[OfferScenario]) -> list[dict]:
    """The scenarios side by side, one row each, in the order they were built."""
    return [
        {
            "strategies": [strategy.value for strategy in scenario.strategies],
            "skus": [line.sku for line in scenario.lines],
            "quantity": sum(line.quantity for line in scenario.lines),
            "net": scenario.net,
            "shipping": scenario.shipping,
            "total": scenario.total,
            "fit": round(scenario.fit, 2),
            "days": scenario.days,
            "availability": scenario.availability.value,
            "risk": scenario.risk.value,
        }
        for scenario in scenarios
    ]


# ── Scoring ───────────────────────────────────────────────────────────────────


def _spreads(requirements: CustomerRequirements, products: list[dict]) -> dict[str, float]:
    """The range each named specification covers across these candidates.

    Overshoot has to be measured against something, and the candidates on the table are
    the only honest yardstick: it makes the score comparable within one request, which is
    the only place it is ever used.
    """
    spreads = {}
    for constraint in requirements.constraints:
        if not is_numeric(constraint.key):
            continue
        held = [
            product["specs"][constraint.key]
            for product in products
            if constraint.key in (product.get("specs") or {})
        ]
        spreads[constraint.key] = float(max(held) - min(held)) if held else 0.0

    return spreads


def _fit(
    requirements: CustomerRequirements, specs: dict, spreads: dict[str, float]
) -> tuple[float, list[str]]:
    """How close a product sits to what was asked, and what it fails outright.

    A request that names nothing fits everything equally, and the retrieval order is left
    to speak for itself.
    """
    if not requirements.constraints:
        return 1.0, []

    penalties = []
    missing = []
    for constraint in requirements.constraints:
        held = specs.get(constraint.key)
        if held is None or not _satisfies(constraint, held):
            penalties.append(1.0)
            missing.append(f"{constraint.key} {constraint.op} {constraint.value}")
            continue

        penalties.append(_overshoot(constraint, held, spreads.get(constraint.key, 0.0)))

    return round(1.0 - sum(penalties) / len(penalties), 4), missing


def _satisfies(constraint: Constraint, held) -> bool:
    if constraint.key in ORDERED_LABELS:
        order = ORDERED_LABELS[constraint.key]
        if held not in order:
            return False
        return _compare(constraint.op, order.index(held), order.index(constraint.value))

    if isinstance(constraint.value, bool):
        return bool(held) == constraint.value

    if isinstance(held, str) or isinstance(constraint.value, str):
        return held == constraint.value

    return _compare(constraint.op, held, constraint.value)


def _compare(op: str, held, wanted) -> bool:
    if op == "eq":
        return held == wanted
    if op == "gte":
        return held >= wanted
    if op == "gt":
        return held > wanted
    if op == "lte":
        return held <= wanted
    return held < wanted


def _overshoot(constraint: Constraint, held, spread: float) -> float:
    """How far past the floor a product sits, as a share of what the candidates cover.

    A ceiling is not overshot by being comfortably under it, and `eq` leaves no room to
    overshoot at all, so both cost nothing.
    """
    if constraint.op not in ("gte", "gt"):
        return 0.0

    if constraint.key in ORDERED_LABELS:
        order = ORDERED_LABELS[constraint.key]
        above = len(order) - 1 - order.index(constraint.value)
        steps = order.index(held) - order.index(constraint.value)
        return steps / above if above else 0.0

    if not spread:
        return 0.0

    return min(1.0, (float(held) - float(constraint.value)) / spread)


# ── Pricing one candidate ─────────────────────────────────────────────────────


def _price(
    product: dict,
    requirements: CustomerRequirements,
    spreads: dict[str, float],
    suppliers: dict[str, dict],
    zone: Zone,
    quantity: int,
    before_cut_off: bool,
) -> Priced:
    """One candidate turned into a line, a date and a risk."""
    fit, missing = _fit(requirements, product.get("specs") or {}, spreads)
    sources, availability, notes = _allocate(product, quantity, zone, before_cut_off)
    supplier = suppliers.get(product.get("supplier_code") or "", {})
    days = _days(zone, sources, supplier, before_cut_off, availability != Availability.UNKNOWN)

    line = OfferLine(
        sku=product["sku"],
        description=product["description"],
        quantity=quantity,
        unit_price=float(product.get("price") or 0.0),
        sources=sources,
    )
    risk, told = _risk(availability, supplier, requirements)

    return Priced(
        product=product,
        zone=zone,
        fit=fit,
        missing=missing,
        lines=[line],
        availability=availability,
        days=days,
        risk=risk,
        transfer=max(transfer_cost(zone, _from(source)) for source in sources),
        notes=notes + told,
    )


def _allocate(
    product: dict, quantity: int, zone: Zone, before_cut_off: bool
) -> tuple[list[Allocation], Availability, list[str]]:
    """Where the quantity comes from: a serving warehouse first, then wherever else.

    Filling an order out of two warehouses is the one combination this builder makes. It
    is the only one the catalogue's own data supports — quantities add up across
    warehouses, lengths and wattages do not add up across products.
    """
    held = product.get("warehouses") or []
    if not held:
        return [Allocation(warehouse=None, quantity=quantity)], Availability.UNKNOWN, [
            "the warehouse system has no record for this product"
        ]

    ordered = sorted(held, key=lambda entry: _first(entry, zone))

    sources = []
    left = quantity
    for entry in ordered:
        if left <= 0:
            break
        taken = min(left, entry["quantity"])
        if taken > 0:
            sources.append(Allocation(warehouse=Warehouse(entry["warehouse"]), quantity=taken))
            left -= taken

    notes = []
    if left > 0:
        sources.append(Allocation(warehouse=None, quantity=left))
        notes.append(f"{left} of {quantity} are not in any warehouse and would be ordered")

    if len(sources) > 1 and all(source.warehouse is not None for source in sources):
        notes.append(f"{quantity} covered from {len(sources)} warehouses")

    return sources, _availability(sources, zone, before_cut_off), notes


def _first(entry: dict, zone: Zone) -> tuple:
    """A serving warehouse first, then the fullest, then by name so two runs agree."""
    return (
        not serves(zone, Warehouse(entry["warehouse"])),
        -entry["quantity"],
        entry["warehouse"],
    )


def _availability(
    sources: list[Allocation], zone: Zone, before_cut_off: bool
) -> Availability:
    if any(source.warehouse is None for source in sources):
        return Availability.ORDERED
    if all(serves(zone, source.warehouse) for source in sources):
        if all(same_day(zone, source.warehouse, before_cut_off) for source in sources):
            return Availability.SAME_DAY
        return Availability.IN_STOCK

    return Availability.TRANSFER


def _days(
    zone: Zone, sources: list[Allocation], supplier: dict, before_cut_off: bool, dated: bool
) -> int | None:
    """The slowest part of the order sets the date: it ships when all of it is there.

    A product the warehouse system has never heard of gets no date. Reading its silence as
    an empty shelf and quoting the supplier's lead time would turn a gap in the data into
    a promise.
    """
    lead = supplier.get("lead_time_days")
    if not dated or lead is None:
        return None

    return max(
        working_days(zone, _from(source), lead_time=lead, before_cut_off=before_cut_off)
        for source in sources
    )


def _risk(
    availability: Availability, supplier: dict, requirements: CustomerRequirements
) -> tuple[Risk, list[str]]:
    """What the promise rests on beyond a warehouse shelf."""
    reliability = float(supplier.get("reliability_score") or 1.0)

    if availability == Availability.ORDERED:
        if requirements.immediate and not promises_urgent(reliability):
            return Risk.HIGH, [
                f"{supplier.get('code', 'the supplier')} does not commit to urgent orders"
            ]
        return Risk.MEDIUM, [f"part of the quantity is ordered from {supplier.get('code', '?')}"]

    if availability == Availability.UNKNOWN:
        return Risk.MEDIUM, ["stock is unknown, which is not the same as none"]

    if availability == Availability.TRANSFER:
        return Risk.LOW, ["stock moves between warehouses before it ships"]

    return Risk.LOW, []


def _from(source: Allocation) -> Warehouse | None:
    return source.warehouse


# ── The five readings ─────────────────────────────────────────────────────────


def _cheapest(candidates: list[Priced], requirements: CustomerRequirements) -> Priced | None:
    """The least the customer can pay and still get what they asked for."""
    return min(
        candidates,
        key=lambda one: (len(one.missing), one.total, -one.fit, one.lines[0].sku),
        default=None,
    )


def _closest(candidates: list[Priced], requirements: CustomerRequirements) -> Priced | None:
    """Nearest to the request, with nothing to spare and nothing missing."""
    return min(
        candidates,
        key=lambda one: (len(one.missing), -one.fit, one.total, one.lines[0].sku),
        default=None,
    )


def _most_for_the_money(
    candidates: list[Priced], requirements: CustomerRequirements
) -> Priced | None:
    """The most fit per euro, inside the budget when the request named one."""
    inside = [
        one
        for one in candidates
        if requirements.price_max is None or one.lines[0].unit_price <= requirements.price_max
    ]
    return max(
        inside or candidates,
        key=lambda one: (
            -len(one.missing),
            one.fit / one.total if one.total else 0.0,
            -one.total,
            one.lines[0].sku,
        ),
        default=None,
    )


def _soonest(candidates: list[Priced], requirements: CustomerRequirements) -> Priced | None:
    """In the customer's hands first, and cheapest among those that arrive together.

    A candidate with no date is not the soonest. It is the one nobody can promise.
    """
    datable = [one for one in candidates if one.days is not None]
    return min(
        datable,
        key=lambda one: (
            len(one.missing),
            one.days,
            _weight(one.risk),
            one.total,
            one.lines[0].sku,
        ),
        default=None,
    )


def _step_up(candidates: list[Priced], requirements: CustomerRequirements) -> Priced | None:
    """The top of what the catalogue holds for this request, for the customer who asks."""
    return max(
        candidates,
        key=lambda one: (-len(one.missing), one.total, one.fit, one.lines[0].sku),
        default=None,
    )


def _weight(risk: Risk) -> int:
    return {Risk.LOW: 0, Risk.MEDIUM: 1, Risk.HIGH: 2}[risk]


def _mark(one: Priced) -> tuple:
    """What makes two picks the same offer rather than two."""
    return tuple(
        (line.sku, line.quantity, tuple(_taken(source) for source in line.sources))
        for line in one.lines
    )


def _taken(source: Allocation) -> tuple:
    return source.warehouse, source.quantity


def _scenario(strategies: list[Strategy], one: Priced) -> OfferScenario:
    return OfferScenario(
        strategies=strategies,
        lines=one.lines,
        shipping=shipping(one.zone, one.net),
        fit=one.fit,
        availability=one.availability,
        days=one.days,
        risk=one.risk,
        transfer_cost=one.transfer,
        notes=list(one.notes),
    )
