from services.data_service.categories import Category
from services.data_service.discounts import cap, needs_approval, rate, volume_rate


def test_a_band_starts_at_its_own_figure_and_two_bands_never_add_up():
    """The policy prints «Παραγγελία 800 € παίρνει 3%», so 799,99 € is still the band below."""
    assert volume_rate(799.99) == 0.0
    assert volume_rate(800.0) == 0.03
    assert volume_rate(4000.0) == 0.05
    assert volume_rate(15000.0) == 0.08


def test_the_category_ceiling_erases_the_band_above_it():
    """The same 8.139,92 € order earns 7%, and a UPS line is still given 5%."""
    assert volume_rate(8139.92) == 0.07
    assert rate(8139.92, Category.DATA) == 0.07
    assert rate(8139.92, Category.UPS) == cap(Category.UPS) == 0.05


def test_approval_is_read_on_the_band_and_not_on_what_the_ceiling_let_through():
    """Two orders given the same 5%: the one whose band is 7% is not the salesperson's."""
    assert rate(8139.92, Category.UPS) == rate(4000.0, Category.PSU) == 0.05
    assert needs_approval(8139.92)
    assert not needs_approval(4000.0)
