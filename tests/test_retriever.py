import pytest

from services.offer_service.clients import catalog
from services.offer_service.rag import embeddings, indexer, retriever, store
from services.offer_service.rag import vectors as kept
from services.offer_service.requirements import Constraint, CustomerRequirements

CATALOGUE = [
    {
        "sku": "PWR-1000",
        "category": "POWER",
        "brand": "Kyma",
        "description": "Καλώδιο ρεύματος 3x2.5mm 25m 2kW IP67",
        "web_description": "Τριπολικό καλώδιο για εξωτερικό χώρο.",
        "supplier_code": "SUP-01",
        "price": 96.2,
        "stock_total": 40,
        "specs": {"cores": 3, "section_mm": 2.5, "length_m": 25, "watt": 2000, "ip_rating": "IP67"},
    },
    {
        "sku": "PWR-1001",
        "category": "POWER",
        "brand": "Kyma",
        "description": "Καλώδιο ρεύματος 3x1.5mm 5m 750W IP44",
        "web_description": "Τριπολικό καλώδιο γραφείου.",
        "supplier_code": "SUP-02",
        "price": 18.4,
        "stock_total": None,
        "specs": {"cores": 3, "section_mm": 1.5, "length_m": 5, "watt": 750, "ip_rating": "IP44"},
    },
    {
        "sku": "PWR-1002",
        "category": "POWER",
        "brand": "Nordion",
        "description": "Καλώδιο ρεύματος 5x6.0mm 50m 3kW IP67",
        "web_description": "Πενταπολικό καλώδιο εργοταξίου.",
        "supplier_code": "SUP-03",
        "price": 210.0,
        "stock_total": 7,
        "specs": {"cores": 5, "section_mm": 6.0, "length_m": 50, "watt": 3000, "ip_rating": "IP67"},
    },
]

AXES = {
    "PWR-1000": [1.0, 0.0, 0.0],
    "PWR-1001": [0.0, 1.0, 0.0],
    "PWR-1002": [0.0, 0.0, 1.0],
}

PRICED = [
    {"sku": "PWR-1000", "price": 96.2, "stock_total": 40},
    {"sku": "PWR-1001", "price": 18.4, "stock_total": None},
    {"sku": "PWR-1002", "price": 210.0, "stock_total": 7},
]


def asked(request: str, **changes) -> CustomerRequirements:
    return CustomerRequirements(request=request, **changes)


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    """No catalogue service, no OpenAI, no real store — the request's vector is ours to aim."""
    monkeypatch.setattr(store, "CHROMA_PATH", tmp_path / "chroma")
    monkeypatch.setattr(store, "_client", None)
    monkeypatch.setattr(kept, "PRODUCT_FILE", tmp_path / "card_vectors.npz")
    monkeypatch.setattr(catalog, "fetch_all", lambda: CATALOGUE)
    monkeypatch.setattr(catalog, "lookup", lambda skus: [r for r in PRICED if r["sku"] in skus])
    monkeypatch.setattr(embeddings, "embed", lambda texts, purpose: [_aimed(t) for t in texts])
    yield
    store._client = None


def _aimed(text: str) -> list[float]:
    """A card sits on its own axis; a request is aimed at the last code it names."""
    for sku, axis in AXES.items():
        if text.startswith(f"{sku} ·"):
            return axis

    named = [sku for sku in AXES if sku in text]
    return AXES[named[-1]] if named else [0.0, 0.0, 0.0]


def test_an_unbuilt_index_says_so_rather_than_answering_nothing():
    """A clone that has not indexed would otherwise look like a catalogue with no cables."""
    with pytest.raises(retriever.IndexNotBuilt):
        retriever.search(asked("καλώδιο ρεύματος"))


def test_a_product_the_constraints_exclude_never_reaches_either_ranking():
    indexer.rebuild_products()

    found = retriever.search(
        asked("καλώδιο", category="POWER", constraints=[Constraint(key="cores", value=3)])
    )

    assert [match.sku for match in found.matches] == ["PWR-1000", "PWR-1001"]
    assert found.trace["eligible"] == 2


def test_a_request_nothing_satisfies_comes_back_with_what_each_concession_costs():
    """No three-core cable reaches 2500W. Both ways of bending are offers, not mistakes."""
    indexer.rebuild_products()

    found = retriever.search(
        asked(
            "τριπολικό καλώδιο 2.5kW",
            category="POWER",
            constraints=[
                Constraint(key="cores", value=3),
                Constraint(key="watt", op="gte", value=2500),
            ],
        )
    )

    assert sorted(match.sku for match in found.matches) == ["PWR-1000", "PWR-1001", "PWR-1002"]
    assert found.trace["concessions"] == {
        "cores eq 3": ["PWR-1002"],
        "watt gte 2500": ["PWR-1000", "PWR-1001"],
    }


def test_a_request_with_nothing_to_search_costs_nothing(monkeypatch):
    """No switches in the catalogue and no constraint to loosen: do not pay for a vector."""
    indexer.rebuild_products()
    monkeypatch.setattr(
        embeddings, "embed", lambda texts, purpose: pytest.fail("the request was embedded")
    )

    found = retriever.search(asked("switch", category="NETWORK"))

    assert found.matches == []
    assert found.trace["eligible"] == 0


def test_neither_half_can_bury_what_the_other_put_first():
    """The guarantee the merge exists for: the n-th of each half lands no worse than 2n."""
    words = [f"A{n}" for n in range(20)]
    meaning = [f"B{n}" for n in range(20)]

    merged = retriever._merged(words, meaning)

    assert all(
        merged.index(half[n]) <= 2 * n + 1 for half in (words, meaning) for n in range(len(half))
    )


def test_both_halves_of_the_search_reach_the_merge():
    """The word side is handed a code, the meaning side is aimed elsewhere: both survive."""
    indexer.rebuild_products()

    found = retriever.search(asked("PWR-1001 εργοταξίου PWR-1002"))
    ordered = [match.sku for match in found.matches]

    assert found.trace["by_word"][0] == "PWR-1001"
    assert found.trace["by_meaning"][0] == "PWR-1002"
    assert set(ordered[:2]) == {"PWR-1001", "PWR-1002"}


def test_the_end_of_a_range_is_sorted_rather_than_ranked(monkeypatch):
    """The catalogue answers "the longest one" exactly, so neither half is asked to guess."""
    indexer.rebuild_products()
    monkeypatch.setattr(
        embeddings, "embed", lambda texts, purpose: pytest.fail("the request was embedded")
    )

    found = retriever.search(
        asked("το πιο μακρύ καλώδιο", category="POWER", order={"key": "length_m", "end": "max"})
    )

    assert [match.sku for match in found.matches] == ["PWR-1002", "PWR-1000", "PWR-1001"]
    assert found.trace["ordered_by"] == "length_m max"


def test_the_price_and_the_stock_come_from_the_catalogue():
    """Neither is in the card, and neither may be: both change without a reindex."""
    indexer.rebuild_products()

    found = retriever.search(asked("καλώδιο ρεύματος"))
    priced = {match.sku: (match.price, match.stock) for match in found.matches}

    assert priced["PWR-1001"] == (18.4, None)
    assert priced["PWR-1002"] == (210.0, 7)
    assert all("price" not in match.metadata for match in found.matches)
