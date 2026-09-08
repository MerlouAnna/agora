"""
Delivery registry
=================
Where an order goes and how long it takes to get there: the stores, the four destination
zones, and the arithmetic the delivery terms document lays out. Every number here is read
off that document except the zone each warehouse serves, which it leaves unsaid.
"""

from datetime import time
from enum import StrEnum

from services.data_service.categories import Warehouse


class Zone(StrEnum):
    """The four destinations the delivery terms price and time separately."""

    ATTICA = "ATTICA"
    THESSALONIKI = "THESSALONIKI"
    MAINLAND = "MAINLAND"
    ISLANDS = "ISLANDS"


class Store(StrEnum):
    """The branches an order can be raised from."""

    ATHENS = "ATHENS"
    PIRAEUS = "PIRAEUS"
    THESSALONIKI = "THESSALONIKI"
    PATRA = "PATRA"
    TRIPOLI = "TRIPOLI"
    LARISA = "LARISA"
    HERAKLION = "HERAKLION"


STORE_ZONES = {
    Store.ATHENS: Zone.ATTICA,
    Store.PIRAEUS: Zone.ATTICA,
    Store.THESSALONIKI: Zone.THESSALONIKI,
    Store.PATRA: Zone.MAINLAND,
    Store.TRIPOLI: Zone.MAINLAND,
    Store.LARISA: Zone.MAINLAND,
    Store.HERAKLION: Zone.ISLANDS,
}

# Working days from a warehouse holding the product to the destination.
TRANSIT = {
    Warehouse.ATH_01: {Zone.ATTICA: 1, Zone.THESSALONIKI: 2, Zone.MAINLAND: 2, Zone.ISLANDS: 3},
    Warehouse.ATH_02: {Zone.ATTICA: 1, Zone.THESSALONIKI: 2, Zone.MAINLAND: 2, Zone.ISLANDS: 3},
    Warehouse.THE_01: {Zone.ATTICA: 2, Zone.THESSALONIKI: 1, Zone.MAINLAND: 2, Zone.ISLANDS: 3},
    Warehouse.PAT_01: {Zone.ATTICA: 2, Zone.THESSALONIKI: 3, Zone.MAINLAND: 2, Zone.ISLANDS: 4},
}

# Ours, not the document's: it names an "αποθήκη εξυπηρέτησης" per destination and never
# says which. These reproduce its own worked example. The two Attica warehouses count as
# one wherever they appear — the same transit row, and no transfer between them.
SERVES = {
    Zone.ATTICA: (Warehouse.ATH_01, Warehouse.ATH_02),
    Zone.THESSALONIKI: (Warehouse.THE_01,),
    Zone.MAINLAND: (Warehouse.PAT_01,),
    Zone.ISLANDS: (Warehouse.ATH_01, Warehouse.ATH_02),
}

TRANSFER_DAYS = 1
TRANSFER_DAYS_TO_ISLAND = 2
TRANSFER_COST = 15.0

RECEIVING_DAYS = 1

SHIPPING = {Zone.ATTICA: 5.0, Zone.THESSALONIKI: 7.0, Zone.MAINLAND: 9.0, Zone.ISLANDS: 14.0}
SHIPPING_FREE_FROM = 300.0

SAME_DAY_FROM = (Warehouse.ATH_01, Warehouse.ATH_02)
SAME_DAY_ZONE = Zone.ATTICA
CUT_OFF = time(13, 0)

URGENT_RELIABILITY = 0.80


def zone_of(store: Store) -> Zone:
    return STORE_ZONES[store]


def working_days(
    zone: Zone,
    held_in: Warehouse | None,
    lead_time: int | None = None,
    before_cut_off: bool = True,
) -> int:
    """How long the customer waits, counted the way the delivery terms count it.

    Args:
        zone: Where the order is going.
        held_in: The warehouse the stock is coming out of, or None when there is none.
        lead_time: The supplier's receiving time, needed only when there is no stock.
        before_cut_off: Whether the order is confirmed by 13:00, which same-day needs.

    Returns:
        Working days, where 0 means the same working day.

    Raises:
        ValueError: There is no stock and no lead time to order against.
    """
    if held_in is None:
        if lead_time is None:
            raise ValueError("a product in no warehouse needs its supplier's lead time")
        return lead_time + RECEIVING_DAYS + TRANSIT[SERVES[zone][0]][zone]

    if same_day(zone, held_in, before_cut_off):
        return 0

    direct = TRANSIT[held_in][zone]
    if serves(zone, held_in):
        return direct

    moved = TRANSFER_DAYS_TO_ISLAND if zone == Zone.ISLANDS else TRANSFER_DAYS
    return moved + direct


def same_day(zone: Zone, held_in: Warehouse | None, before_cut_off: bool = True) -> bool:
    """Whether this counts as άμεση παράδοση, which is narrower than being in stock."""
    return zone == SAME_DAY_ZONE and held_in in SAME_DAY_FROM and before_cut_off


def serves(zone: Zone, warehouse: Warehouse) -> bool:
    """Whether this warehouse ships to that destination without moving the stock first."""
    return warehouse in SERVES[zone]


def transfer_cost(zone: Zone, held_in: Warehouse | None) -> float:
    """What the internal move costs the company. The customer never sees it."""
    if held_in is None or serves(zone, held_in):
        return 0.0

    return TRANSFER_COST


def shipping(zone: Zone, net: float) -> float:
    """Carriage, which a large enough order stops paying."""
    return 0.0 if net >= SHIPPING_FREE_FROM else SHIPPING[zone]


def promises_urgent(reliability: float) -> bool:
    """Whether a supplier can be committed to for an urgent order at all."""
    return reliability >= URGENT_RELIABILITY
