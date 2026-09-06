import pytest

from services.offer_service.clients import catalog
from services.offer_service.rag import embeddings, indexer, store

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
]


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    """No catalogue service, no OpenAI, no real store — only the wiring between them."""
    monkeypatch.setattr(store, "CHROMA_PATH", tmp_path / "chroma")
    monkeypatch.setattr(store, "_client", None)
    monkeypatch.setattr(catalog, "fetch_all", lambda: CATALOGUE)
    monkeypatch.setattr(
        embeddings, "embed", lambda texts, purpose: [[float(len(t)), 0.5] for t in texts]
    )
    yield
    store._client = None


def test_every_product_reaches_the_store_with_its_card():
    report = indexer.rebuild_products()
    held = store.collection(store.PRODUCTS).get(include=["documents", "metadatas"])
    cards = dict(zip(held["ids"], held["documents"] or [], strict=True))
    categories = [dict(metadata)["category"] for metadata in held["metadatas"] or []]

    assert report["products"] == 2
    assert sorted(cards) == ["PWR-1000", "PWR-1001"]
    assert all(card.startswith(sku) for sku, card in cards.items())
    assert categories == ["POWER", "POWER"]


def test_indexing_twice_leaves_one_copy_of_each_product():
    indexer.rebuild_products()
    indexer.rebuild_products()

    assert store.counts()[store.PRODUCTS] == 2


def test_an_empty_catalogue_is_reported_rather_than_indexed(monkeypatch):
    monkeypatch.setattr(catalog, "fetch_all", list)

    assert indexer.rebuild_products()["products"] == 0
    assert store.counts()[store.PRODUCTS] == 0
