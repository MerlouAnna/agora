"""
Offer types
===========
What a scenario is once it has been built: the lines a customer would sign, where each
quantity comes from, what it costs, when it arrives, and what could go wrong with it.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from services.data_service import discounts
from services.data_service.categories import Warehouse
from services.data_service.delivery import Zone, same_day, serves


class Strategy(StrEnum):
    """The five ways of reading the same candidates."""

    BEST_BUDGET = "best-budget"
    BEST_TECHNICAL = "best-technical"
    CHEAPEST = "cheapest-acceptable"
    BEST_AVAILABILITY = "best-availability"
    PREMIUM = "premium-alternative"


class Availability(StrEnum):
    """Where the quantity is coming from, which is what decides the delivery date."""

    SAME_DAY = "same-day"
    IN_STOCK = "in-stock"
    TRANSFER = "transfer"
    ORDERED = "ordered"
    UNKNOWN = "unknown"


class Risk(StrEnum):
    """How much of the promise rests on something outside the warehouse."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class Allocation:
    """One part of a line's quantity, and the warehouse it leaves from.

    A warehouse of None means the quantity does not exist yet and is being ordered.
    """

    warehouse: Warehouse | None
    quantity: int


@dataclass(frozen=True)
class OfferLine:
    """One product on the offer, priced as the catalogue prices it right now."""

    sku: str
    description: str
    quantity: int
    unit_price: float
    sources: list[Allocation]

    @property
    def line_total(self) -> float:
        return round(self.unit_price * self.quantity, 2)


@dataclass(frozen=True)
class OfferScenario:
    """One offer, complete enough to be put in front of a customer or refused.

    `days` counts working days, where 0 is the same working day and None means the order
    cannot be dated. `net` is the catalogue value, which is what both business documents
    mean by καθαρή αξία — the discount comes off it and the carriage threshold reads it.
    `transfer_cost` is the company's own and never the customer's, `needs_approval` is read
    on the band and not on the discount the ceiling let through, and `strategies` holds every
    reading that landed on this offer.
    """

    strategies: list[Strategy]
    lines: list[OfferLine]
    shipping: float
    fit: float
    availability: Availability
    days: int | None
    risk: Risk
    discount_rate: float = 0.0
    transfer_cost: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def net(self) -> float:
        return round(sum(line.line_total for line in self.lines), 2)

    @property
    def discount(self) -> float:
        return round(self.net * self.discount_rate, 2)

    @property
    def needs_approval(self) -> bool:
        """Whether this order's band is past what the salesperson signs off alone."""
        return discounts.needs_approval(self.net)

    @property
    def total(self) -> float:
        return round(self.net - self.discount + self.shipping, 2)


def availability_of(
    sources: list[Allocation], zone: Zone, before_cut_off: bool = True
) -> Availability:
    """What an allocation amounts to, which is what decides the delivery date.

    Άμεση παράδοση is narrower than being in stock: Attica only, out of the two Attica
    warehouses, and confirmed by the cut-off.
    """
    if any(source.warehouse is None for source in sources):
        return Availability.ORDERED

    if all(serves(zone, source.warehouse) for source in sources):
        if all(same_day(zone, source.warehouse, before_cut_off) for source in sources):
            return Availability.SAME_DAY
        return Availability.IN_STOCK

    return Availability.TRANSFER
