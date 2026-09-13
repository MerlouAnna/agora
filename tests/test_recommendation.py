import pytest

from services.data_service.delivery import Store
from services.offer_service import recommendation
from services.offer_service import scenario_builder as builder
from services.offer_service.rag import policies
from services.offer_service.recommendation import Written
from services.offer_service.requirements import Constraint, CustomerRequirements

SUPPLIERS = {"SUP-01": {"code": "SUP-01", "lead_time_days": 3, "reliability_score": 0.96}}

CHEAP = {
    "sku": "SWT-1025",
    "category": "NETWORK",
    "brand": "Delta Line",
    "description": "Switch 24 θυρών 1000Mbps PoE",
    "price": 57.30,
    "supplier_code": "SUP-01",
    "specs": {"ports": 24, "speed_mbps": 1000, "poe": "true", "managed": "false"},
    "warehouses": [{"warehouse": "ATH-01", "quantity": 40}],
}
DEARER = CHEAP | {"sku": "SWT-1022", "price": 826.10, "description": "Switch 48 θυρών PoE managed"}


def asked(**changes) -> CustomerRequirements:
    return CustomerRequirements(
        request="Θέλω switch 24 θυρών με PoE.", category="NETWORK", **changes
    )


def offers(requirements=None):
    return builder.build(requirements or asked(), [CHEAP, DEARER], SUPPLIERS, Store.ATHENS)


def answers(*written):
    """A model that gives these answers in turn, and writes down what it was told to fix."""
    given, told = list(written), []

    def ask(context: dict, problem: str | None) -> Written:
        told.append(problem)
        return given.pop(0)

    return ask, told


def good(sku="SWT-1025", text="Το SWT-1025 στα 57.30 ευρώ, παράδοση αυθημερόν."):
    return Written(sku=sku, because="φθηνότερο και σε απόθεμα", watch_out=[], text=text)


def test_nothing_to_recommend_is_not_something_to_invent():
    """The graph decides what to do with an empty offer set; this node refuses to fill it."""
    with pytest.raises(recommendation.NoOffers):
        recommendation.recommend([], asked(), ask=answers(good())[0])


def test_a_product_that_is_not_on_the_table_is_sent_back():
    """The one thing the prompt forbids outright, so the code must not rely on the prompt."""
    ask, told = answers(good(sku="SWT-9999"), good())

    written = recommendation.recommend(offers(), asked(), ask=ask)

    assert written.sku == "SWT-1025"
    assert written.rounds_used == 2
    assert told[0] is None
    assert "SWT-9999 is not one of the offers" in told[1]


def test_a_figure_that_appears_nowhere_is_sent_back_even_when_it_is_nearly_right():
    """57.30 rounded to 57 is a number the salesperson would have to defend and cannot."""
    ask, told = answers(good(text="Το SWT-1025 στα 57 ευρώ."), good())

    written = recommendation.recommend(offers(), asked(), ask=ask)

    assert written.rounds_used == 2
    assert "57 appears nowhere" in told[1]


def test_an_answer_that_never_stays_inside_the_data_is_given_up_on():
    """Three rounds and then nothing, rather than a plausible offer nobody can stand behind."""
    ask, _ = answers(*[good(sku="SWT-9999")] * 3)

    with pytest.raises(recommendation.RecommendationFailed):
        recommendation.recommend(offers(), asked(), ask=ask)


def test_a_figure_written_the_way_greek_writes_it_is_the_same_figure():
    """3.656,44 is one number, not a 3,66 and a 44 — and the offers are priced in Greek."""
    built = builder.build(asked(quantity=5), [DEARER], SUPPLIERS, Store.ATHENS)
    greek = f"{built[0].total:,.2f}".translate(str.maketrans(",.", ".,"))
    ask, told = answers(good(sku="SWT-1022", text=f"Το SWT-1022, σύνολο {greek} ευρώ."))

    written = recommendation.recommend(built, asked(quantity=5), ask=ask)

    assert "." in greek and "," in greek
    assert written.rounds_used == 1
    assert told == [None]


def test_the_numbers_the_request_itself_names_are_allowed():
    """«24 θύρες» is the customer's own word and belongs in the answer."""
    wanted = asked(constraints=[Constraint(key="ports", op="gte", value=24)])
    ask, told = answers(good(text="Το SWT-1025 έχει 24 θύρες, στα 57.30 ευρώ."))

    written = recommendation.recommend(offers(wanted), wanted, ask=ask)

    assert written.rounds_used == 1
    assert told == [None]


def test_the_sections_that_travel_are_the_ones_the_offers_put_in_play():
    """A heading that stops existing has to fail here rather than silently send nothing."""
    named = {(document, heading) for document, heading, _ in recommendation.GROUNDS}
    held = {
        (passage.metadata["document"], passage.metadata["section"])
        for passage in policies.read_all()
    }

    assert named <= held

    sections = {passage.metadata["section"] for passage in recommendation.grounds(offers())}

    assert "Άμεση παράδοση" in sections
    assert "Έγκριση πάνω από το όριο" not in sections
