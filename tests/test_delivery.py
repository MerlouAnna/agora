from services.data_service.categories import Warehouse
from services.data_service.delivery import TRANSIT, Zone, working_days


def test_a_transfer_never_beats_the_shelf_the_stock_already_sits_on():
    """A move can only cost time. Reading the serving warehouse's row instead of the
    holding one's promised PAT-01 → Θεσσαλονίκη in 2 days where the table prints 3."""
    for zone in Zone:
        for warehouse in Warehouse:
            assert working_days(zone, warehouse, before_cut_off=False) >= TRANSIT[warehouse][zone]


def test_the_transfer_day_lands_on_top_of_the_holding_warehouses_own_row():
    """A serving warehouse ships on its own row; any other pays the move on top of it.

    The two Attica warehouses count as one, so neither of them pays it to reach an island.
    """
    assert working_days(Zone.THESSALONIKI, Warehouse.THE_01) == 1
    assert working_days(Zone.THESSALONIKI, Warehouse.PAT_01) == 4
    assert working_days(Zone.ISLANDS, Warehouse.ATH_02) == 3
    assert working_days(Zone.ISLANDS, Warehouse.PAT_01) == 6
