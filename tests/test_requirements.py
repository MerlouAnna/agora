import pytest
from pydantic import ValidationError

from services.data_service.categories import Category
from services.offer_service.rag import filters
from services.offer_service.requirements import Constraint, CustomerRequirements, Ordering


def asked(**changes) -> CustomerRequirements:
    return CustomerRequirements(request="δοκιμή", **changes)


def test_a_specification_the_catalogue_does_not_carry_is_refused():
    with pytest.raises(ValidationError, match="voltage"):
        Constraint(key="voltage", op="gte", value=400)


def test_a_plain_label_takes_neither_a_comparison_nor_a_value_of_its_own():
    """SFX is not more than ATX, and «offline» is not a topology this catalogue sells.

    The refusal carries the vocabulary, because that sentence is what the extractor is
    handed to correct itself with.
    """
    with pytest.raises(ValidationError, match="no order"):
        Constraint(key="form_factor", op="gte", value="SFX")

    with pytest.raises(ValidationError, match="no order"):
        Ordering(key="form_factor", end="max")

    with pytest.raises(ValidationError, match=r"\['line-interactive', 'online'\]"):
        Constraint(key="topology", value="offline")


def test_a_number_the_catalogue_never_holds_is_refused():
    """`watt eq 0` is well formed and matches nothing. It came out of a real extraction."""
    with pytest.raises(ValidationError, match="never 0 or less"):
        Constraint(key="watt", value=0)

    with pytest.raises(ValidationError, match="never inf"):
        Constraint(key="watt", op="gte", value=float("inf"))


def test_a_flag_is_on_or_off_rather_than_the_word():
    """The card metadata holds a boolean, so the string "true" would match nothing at all."""
    with pytest.raises(ValidationError, match="on or off"):
        Constraint(key="poe", value="true")

    assert Constraint(key="poe", value=True).value is True


def test_an_ordered_label_becomes_every_value_from_there_up():
    clause = filters.where(asked(constraints=[Constraint(key="ip_rating", op="gte", value="IP54")]))

    assert clause == {"ip_rating": {"$in": ["IP54", "IP67"]}}


def test_a_strict_comparison_stays_strict():
    over = asked(constraints=[Constraint(key="watt", op="gt", value=700)])
    from_here = asked(constraints=[Constraint(key="watt", op="gte", value=700)])

    assert filters.where(over) == {"watt": {"$gt": 700}}
    assert filters.where(from_here) == {"watt": {"$gte": 700}}


def test_a_request_with_nothing_to_filter_on_has_no_filter():
    """A request for the longest cable narrows nothing — the ranking has to answer it."""
    assert filters.where(asked()) is None
    assert filters.where(asked(category=Category.POWER)) == {"category": {"$eq": "POWER"}}


def test_every_condition_has_to_hold_at_once():
    clause = filters.where(
        asked(
            category=Category.NETWORK,
            constraints=[
                Constraint(key="ports", op="gte", value=24),
                Constraint(key="poe", value=True),
            ],
        )
    )

    assert clause == {
        "$and": [
            {"category": {"$eq": "NETWORK"}},
            {"ports": {"$gte": 24}},
            {"poe": {"$eq": True}},
        ]
    }


def test_a_specification_the_named_category_has_no_business_with_is_refused():
    with pytest.raises(ValidationError, match="POWER products have no ports"):
        asked(category=Category.POWER, constraints=[Constraint(key="ports", op="gte", value=24)])
