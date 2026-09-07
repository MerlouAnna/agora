import json
from pathlib import Path

import pytest

from services.offer_service.rag import embeddings, indexer, policies, retriever, store
from services.offer_service.rag import vectors as kept

EVAL_FILE = Path(__file__).resolve().parent / "data" / "policy_eval.json"


@pytest.fixture(scope="module")
def shipped():
    """The ten documents, read once for the whole file — parsing PDFs is not free."""
    return policies.read_all()


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch, shipped):
    """A real read of the shipped documents, into a store of our own, with no model."""
    monkeypatch.setattr(store, "CHROMA_PATH", tmp_path / "chroma")
    monkeypatch.setattr(store, "_client", None)
    monkeypatch.setattr(kept, "POLICY_FILE", tmp_path / "policy_vectors.npz")
    monkeypatch.setattr(policies, "read_all", lambda folder=None: shipped)
    yield
    store._client = None


def towards(word: str):
    """Point the meaning side at whatever mentions a word, so the halves agree."""
    return lambda texts, purpose: [[1.0, 0.0] if word in text else [0.0, 1.0] for text in texts]


def test_every_answer_the_eval_expects_is_a_section_that_still_exists(shipped):
    """A passage id counts sections, so a re-render with one more heading moves them all."""
    cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))["cases"]
    wanted = {answer for case in cases for answer in case["expected"]}

    assert wanted <= {passage.id for passage in shipped}


def test_documents_that_were_never_indexed_say_so_rather_than_answering_nothing():
    with pytest.raises(retriever.IndexNotBuilt):
        retriever.search_policies("Τι εγγύηση δίνετε;")


def test_a_question_about_the_terms_reaches_the_policy_that_answers_it(monkeypatch):
    monkeypatch.setattr(embeddings, "embed", towards("έκπτωση"))
    indexer.rebuild_policies()

    found, trace = retriever.search_policies("Τι έκπτωση έχει παραγγελία 12.000 ευρώ;")

    assert found[0].metadata["document"] == "politiki-ekptoseon", trace
    assert "15.000 € και άνω | 8%" in " ".join(excerpt.text for excerpt in found), trace
    assert trace["passages"] == 66


def test_a_question_naming_a_product_reaches_its_datasheet(monkeypatch):
    """Every datasheet section carries its code, so the word side can find one by name."""
    monkeypatch.setattr(embeddings, "embed", towards("παράδοση"))
    indexer.rebuild_policies()

    found, trace = retriever.search_policies("Πόση αυτονομία έχει το UPS-1014;", limit=10)

    assert trace["by_word"][0].startswith("datasheet-UPS-1014")
    assert any(excerpt.metadata.get("sku") == "UPS-1014" for excerpt in found)
