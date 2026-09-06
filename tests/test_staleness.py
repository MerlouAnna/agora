import pytest

from services.offer_service.clients import catalog
from services.offer_service.rag import embeddings, indexer, retriever, store
from services.offer_service.rag import vectors as kept
from services.offer_service.requirements import CustomerRequirements

CABLES = [
    {
        "sku": "PWR-1000",
        "category": "POWER",
        "brand": "Kyma",
        "description": "Καλώδιο ρεύματος 3x2.5mm 25m 2kW IP67",
        "web_description": "Τριπολικό καλώδιο για εξωτερικό χώρο.",
        "supplier_code": "SUP-01",
        "specs": {"cores": 3, "section_mm": 2.5, "length_m": 25},
    },
    {
        "sku": "PWR-1001",
        "category": "POWER",
        "brand": "Kyma",
        "description": "Καλώδιο ρεύματος 3x1.5mm 5m 750W IP44",
        "web_description": "Τριπολικό καλώδιο γραφείου.",
        "supplier_code": "SUP-02",
        "specs": {"cores": 3, "section_mm": 1.5, "length_m": 5},
    },
    {
        "sku": "PWR-1002",
        "category": "POWER",
        "brand": "Nordion",
        "description": "Καλώδιο ρεύματος 5x6.0mm 50m 3kW IP67",
        "web_description": "Πενταπολικό καλώδιο εργοταξίου.",
        "supplier_code": "SUP-03",
        "specs": {"cores": 5, "section_mm": 6.0, "length_m": 50},
    },
]

LONGEST = CustomerRequirements(
    request="το πιο μακρύ καλώδιο", category="POWER", order={"key": "length_m", "end": "max"}
)


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    """A store of our own, a catalogue we move under it, and no model on the search path."""
    monkeypatch.setattr(store, "CHROMA_PATH", tmp_path / "chroma")
    monkeypatch.setattr(store, "_client", None)
    monkeypatch.setattr(kept, "PRODUCT_FILE", tmp_path / "card_vectors.npz")
    monkeypatch.setattr(catalog, "lookup", lambda skus: [{"sku": s} for s in skus])
    monkeypatch.setattr(embeddings, "embed", lambda texts, purpose: [[1.0, 0.5] for _ in texts])
    yield
    store._client = None


def catalogue_of(count: int, monkeypatch):
    monkeypatch.setattr(catalog, "fetch_all", lambda: CABLES[:count])
    monkeypatch.setattr(catalog, "stats", lambda: {"products": count})


def test_a_catalogue_that_has_grown_is_indexed_before_it_is_searched(monkeypatch):
    """Generated products reach the database first; a search must not answer without them."""
    catalogue_of(2, monkeypatch)
    indexer.rebuild_products()
    catalogue_of(3, monkeypatch)

    found = retriever.search(LONGEST)

    assert [match.sku for match in found.matches] == ["PWR-1002", "PWR-1000", "PWR-1001"]
    assert found.trace["refreshed"] == {"catalogue": 3, "was_indexed": 2, "embedded": 1}


def test_an_index_that_was_never_built_is_not_built_by_a_search(monkeypatch):
    """226 cards is a bill somebody asks for, never a side effect of one question."""
    catalogue_of(3, monkeypatch)
    monkeypatch.setattr(
        embeddings, "embed", lambda texts, purpose: pytest.fail("a search paid for the index")
    )

    with pytest.raises(retriever.IndexNotBuilt):
        retriever.search(LONGEST)


def test_a_refresh_that_cannot_be_done_does_not_sink_the_search(monkeypatch):
    """A stale index that answers beats no answer, as long as it says it is stale."""
    catalogue_of(2, monkeypatch)
    indexer.rebuild_products()
    monkeypatch.setattr(catalog, "stats", lambda: {"products": 3})
    monkeypatch.setattr(catalog, "fetch_all", _unavailable)

    found = retriever.search(LONGEST)

    assert [match.sku for match in found.matches] == ["PWR-1000", "PWR-1001"]
    assert found.trace["refreshed"] == {"catalogue": 3, "was_indexed": 2, "rebuilt": False}


def _unavailable():
    raise catalog.CatalogueUnavailable("the catalogue is not answering")
