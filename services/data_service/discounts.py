"""
Discount registry
=================
The volume discount an order earns and the ceiling its category puts on that, read off the
discounts policy. Nothing here knows a customer: the contract discount the policy also
describes needs a trading history the catalogue does not carry.
"""

from services.data_service.categories import Category

# Net order value at catalogue prices, and what it earns. An order reads in one band only.
VOLUME_TIERS = [
    (0.0, 0.0),
    (800.0, 0.03),
    (3000.0, 0.05),
    (8000.0, 0.07),
    (15000.0, 0.08),
]

# The most every discount on a product of this category may come to, added together.
CATEGORY_CAPS = {
    Category.POWER: 0.08,
    Category.DATA: 0.08,
    Category.CONNECTORS: 0.08,
    Category.PSU: 0.06,
    Category.NETWORK: 0.06,
    Category.UPS: 0.05,
}

SELF_APPROVED = 0.05


def volume_rate(net: float) -> float:
    """The band the order's net value falls in. Two bands never add up."""
    earned = 0.0
    for floor, rate in VOLUME_TIERS:
        if net >= floor:
            earned = rate

    return earned


def cap(category: Category) -> float:
    return CATEGORY_CAPS[Category(category)]


def rate(net: float, category: Category) -> float:
    """What a line of this category is actually given: its band, held down by its ceiling."""
    return min(volume_rate(net), cap(category))


def needs_approval(net: float) -> bool:
    """Whether the salesperson signs the discount off alone.

    Read on the band and not on what the ceiling let through: the policy names the order
    value, and a narrow category does not turn a large order into the salesperson's own.
    """
    return volume_rate(net) > SELF_APPROVED
