import pytest
from fastapi.testclient import TestClient

from services import security
from services.config import settings
from services.offer_service.clients import catalog
from services.offer_service.main import app
from tests.test_graph import BOTH, CHEAP, DEARER, REQUEST, wire

client = TestClient(app)


@pytest.fixture(autouse=True)
def logged_in(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", "test-only")
    client.headers["Authorization"] = f"Bearer {security.create_access_token('pmoschos')}"


def test_a_request_comes_back_with_the_offers_the_check_let_through(monkeypatch):
    """The table holds what may be shown; every scenario built is accounted for beside it."""
    wire(monkeypatch, BOTH, {DEARER["sku"]: DEARER})

    answered = client.post("/offers/generate", json={"request": REQUEST})
    body = answered.json()

    assert answered.status_code == 200
    assert [row["skus"] for row in body["offers"]] == [[DEARER["sku"]]]
    assert body["recommendation"]["sku"] == DEARER["sku"]
    assert {row["sku"]: row["offerable"] for row in body["checked"]} == {
        CHEAP["sku"]: False,
        DEARER["sku"]: True,
    }
    assert body["refused"] is None
    assert "validate" in body["trace"]


def test_a_request_nothing_answers_is_an_answer_and_not_an_error(monkeypatch):
    """There being no offer is a thing the salesperson is told, not a failure of the service."""
    wire(monkeypatch, {})

    answered = client.post("/offers/generate", json={"request": REQUEST})
    body = answered.json()

    assert answered.status_code == 200
    assert body["offers"] == []
    assert body["recommendation"] is None
    assert body["refused"] == "the catalogue holds nothing that answers the request"


def test_a_catalogue_that_is_not_answering_says_so_rather_than_failing_open(monkeypatch):
    """The graph raises what its steps raise, and the mapping to a status lives here."""
    wire(monkeypatch, BOTH)

    def refuses(skus: list[str]) -> list[dict]:
        raise catalog.CatalogueUnavailable("lookup failed: connection refused")

    monkeypatch.setattr(catalog, "lookup", refuses)

    answered = client.post("/offers/generate", json={"request": REQUEST})

    assert answered.status_code == 503
    assert "connection refused" in answered.json()["detail"]
