import pytest

from services.offer_service import extraction
from services.offer_service.extraction import Extracted, ExtractedConstraint, ExtractedOrdering


def answer(**changes) -> Extracted:
    written = {
        "category": None,
        "quantity": None,
        "constraints": [],
        "order": None,
        "price_min": None,
        "price_max": None,
        "immediate": False,
    }
    return Extracted(**(written | changes))


def replies(*answers):
    """A model that gives these answers in turn, and writes down what it was told to fix."""
    given = list(answers)
    told: list[str | None] = []

    def ask(request: str, problem: str | None) -> Extracted:
        told.append(problem)
        return given.pop(0)

    return ask, told


def test_a_refused_value_goes_back_with_the_vocabulary_and_the_next_round_lands():
    """The refusal is the whole repair prompt: it names the field and lists what it takes."""
    ask, told = replies(
        answer(category="PSU", constraints=[ExtractedConstraint(key="efficiency", op="eq", value="Platinum")]),
        answer(category="PSU", constraints=[ExtractedConstraint(key="efficiency", op="eq", value="80+ Platinum")]),
    )

    found = extraction.extract("τροφοδοτικό Platinum", ask=ask)

    assert told[0] is None
    assert "'Platinum' is not one of ['80+ Bronze', '80+ Gold', '80+ Platinum']" in told[1]
    assert found.requirements.constraints[0].value == "80+ Platinum"
    assert found.trace["rounds"] == 2


def test_a_request_that_never_validates_is_handed_back_rather_than_guessed_at():
    """Searching the whole catalogue on a request nobody could read is not a lesser answer."""
    wrong = answer(category="PSU", constraints=[ExtractedConstraint(key="length_m", op="eq", value="10")])
    ask, told = replies(wrong, wrong, wrong)

    with pytest.raises(extraction.ExtractionFailed, match="PSU products have no length_m"):
        extraction.extract("τροφοδοτικό 10 μέτρα", ask=ask)

    assert len(told) == 3


def test_a_value_of_the_wrong_kind_is_a_refusal_and_not_a_crash():
    """The model writes every value as text, so the number and the flag are ours to read."""
    ask, told = replies(
        answer(constraints=[ExtractedConstraint(key="watt", op="gte", value="δύο χιλιάδες")]),
        answer(constraints=[ExtractedConstraint(key="poe", op="eq", value="ναι")]),
    )

    found = extraction.extract("switch με poe", ask=ask)

    assert "watt is a number, and 'δύο χιλιάδες' is not one" in told[1]
    assert found.requirements.constraints[0].value is True


def test_a_request_the_catalogue_cannot_be_filtered_on_is_a_correct_answer():
    """«Κάτι για μπαλαντέζα» names nothing. The ranking answers it, and nothing is refused."""
    ask, _ = replies(answer())

    found = extraction.extract("κάτι για μπαλαντέζα", ask=ask)

    assert found.requirements.constraints == []
    assert found.requirements.category is None
    assert found.trace == {"rounds": 1}


def test_the_end_of_a_range_survives_the_round_trip():
    """`price` is not a specification, so it is the one ordering the category check waives."""
    ask, _ = replies(
        answer(category="NETWORK", order=ExtractedOrdering(key="price", end="lowest"),
               constraints=[ExtractedConstraint(key="managed", op="eq", value="true")])
    )

    found = extraction.extract("το πιο φθηνό managed switch", ask=ask)

    assert found.requirements.order.key == "price"
    assert found.requirements.order.end == "min"
    assert found.requirements.constraints[0].value is True
