from services.offer_service import extraction, recommendation
from services.offer_service.clients import catalog
from services.offer_service.graph.builder import build_graph
from services.offer_service.graph.state import make_initial_state
from services.offer_service.rag import retriever
from services.offer_service.recommendation import Recommendation
from services.offer_service.requirements import CustomerRequirements

REQUEST = "Θέλω δύο switch 24 θυρών με PoE."

SUPPLIERS = [{"code": "SUP-01", "lead_time_days": 3, "reliability_score": 0.96}]

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

BOTH = {CHEAP["sku"]: CHEAP, DEARER["sku"]: DEARER}


def wire(monkeypatch, *catalogues):
    """The graph with both model calls and the catalogue replaced.

    A second catalogue is what every read after the first one sees, which is a product
    withdrawn between the offer being priced and the offer being checked.

    Returns:
        The list the fake recommender writes what it was given into.
    """
    answering = list(catalogues)
    given = []

    def lookup(skus: list[str]) -> list[dict]:
        rows = answering.pop(0) if len(answering) > 1 else answering[0]
        return [rows[sku] for sku in skus if sku in rows]

    def recommended(offers, requirements, **_) -> Recommendation:
        given.append([one.lines[0].sku for one in offers])
        return Recommendation(
            sku=offers[0].lines[0].sku,
            because="δοκιμή",
            watch_out=[],
            text="δοκιμή",
            rounds_used=1,
            sections=[],
        )

    monkeypatch.setattr(
        extraction,
        "extract",
        lambda request: extraction.Extraction(
            CustomerRequirements(request=request, category="NETWORK", quantity=2), {"rounds": 1}
        ),
    )
    monkeypatch.setattr(
        retriever,
        "search",
        lambda requirements: retriever.Retrieval(
            [
                retriever.Match(row["sku"], row["price"], 40)
                for row in catalogues[0].values()
            ],
            {"merged": list(catalogues[0])},
        ),
    )
    monkeypatch.setattr(catalog, "lookup", lookup)
    monkeypatch.setattr(catalog, "suppliers", lambda: SUPPLIERS)
    monkeypatch.setattr(recommendation, "recommend", recommended)

    return given


def test_the_answer_is_written_only_from_what_the_check_let_through(monkeypatch):
    """Both are offered and one is withdrawn underneath, so the answer may name one.

    Recommending an offer the check withheld is the one failure that would reach a
    customer, so it is the wiring worth a test of its own.
    """
    given = wire(monkeypatch, BOTH, {DEARER["sku"]: DEARER})

    state = build_graph().invoke(make_initial_state(REQUEST))

    assert state["trace"]["build_scenarios"]["built"] == [CHEAP["sku"], DEARER["sku"]]
    assert list(state["trace"]["validate"]["withheld"]) == [CHEAP["sku"]]
    assert given == [[DEARER["sku"]]]
    assert state["recommendation"].sku == DEARER["sku"]


def test_the_trace_holds_every_step_and_not_only_the_last(monkeypatch):
    """Without a reducer on the field each node would overwrite the step before it."""
    wire(monkeypatch, BOTH)

    state = build_graph().invoke(make_initial_state(REQUEST))

    assert sorted(state["trace"]) == [
        "build_scenarios",
        "extract",
        "recommend",
        "retrieve",
        "validate",
    ]
    assert state["trace"]["extract"] == {"rounds": 1}


def test_the_reason_there_is_no_offer_names_where_the_trail_went_cold(monkeypatch):
    """The graph forks once, so that one branch answers for every way of ending empty."""
    given = wire(monkeypatch, {})
    nothing_found = build_graph().invoke(make_initial_state(REQUEST))

    wire(monkeypatch, BOTH, {})
    all_withheld = build_graph().invoke(make_initial_state(REQUEST))

    assert nothing_found["refused"] == "the catalogue holds nothing that answers the request"
    assert all_withheld["refused"] == "every offer that was built is withheld by the check"
    assert nothing_found["recommendation"] is None
    assert all_withheld["recommendation"] is None
    assert given == []
