import pytest

from services.offer_service.rag import store


@pytest.fixture(autouse=True)
def elsewhere(tmp_path, monkeypatch):
    """Never the real store: these tests delete collections."""
    monkeypatch.setattr(store, "CHROMA_PATH", tmp_path / "chroma")
    monkeypatch.setattr(store, "_client", None)
    yield
    store._client = None


def test_a_collection_refuses_to_embed_on_its_own():
    """The only route to a model is embeddings.py, where the call gets written down."""
    collection = store.collection(store.PRODUCTS)

    with pytest.raises(ValueError, match="embedding function"):
        collection.add(ids=["PWR-1000"], documents=["Καλώδιο ρεύματος"])


def test_replacing_a_collection_empties_it():
    store.collection(store.PRODUCTS).add(
        ids=["PWR-1000"], documents=["Καλώδιο ρεύματος"], embeddings=[[0.1, 0.2, 0.3]]
    )
    assert store.counts()[store.PRODUCTS] == 1

    store.replace(store.PRODUCTS)
    assert store.counts()[store.PRODUCTS] == 0


def test_a_collection_never_built_reads_as_empty():
    assert store.counts() == {store.PRODUCTS: 0, store.POLICIES: 0}
