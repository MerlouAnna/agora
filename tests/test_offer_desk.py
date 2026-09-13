import httpx
import pytest
from fastapi.testclient import TestClient

from services import security
from services.config import settings
from services.data_service.categories import SPEC_TYPES
from services.offer_service.domain.models import Availability, Strategy
from services.offer_service.main import app
from tests.test_graph import BOTH, DEARER, REQUEST, wire
from ui import gradio_app as desk

client = TestClient(app)


@pytest.fixture(autouse=True)
def logged_in(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", "test-only")
    client.headers["Authorization"] = f"Bearer {security.create_access_token('pmoschos')}"


def test_the_screen_reads_every_column_the_service_sends(monkeypatch):
    """The two halves drift apart quietly: the table is built from keys the API chooses."""
    wire(monkeypatch, BOTH, {DEARER["sku"]: DEARER})

    body = client.post("/offers/generate", json={"request": REQUEST}).json()
    rows = desk.table(body)

    assert len(rows) == 1
    assert len(rows[0]) == len(desk.OFFERS)
    assert rows[0][0].startswith(DEARER["sku"])
    assert desk.found(body) == "SWT-1025, SWT-1022"
    assert desk.checks(body)[0][1] == "όχι"


def test_money_is_written_the_way_the_business_documents_write_it():
    """A grouping dot read as a decimal point is how this project lost an evening once."""
    assert desk.money(1602.63) == "1.602,63 €"
    assert desk.money(45.78) == "45,78 €"
    assert desk.money(0.0) == "0,00 €"


def test_a_request_with_no_offer_shows_the_reason_rather_than_an_empty_panel(monkeypatch):
    wire(monkeypatch, {})

    body = client.post("/offers/generate", json={"request": REQUEST}).json()

    assert "Καμία προσφορά" in desk.panel(body)
    assert body["refused"] in desk.panel(body)
    assert desk.table(body) == []


def test_the_screen_has_a_greek_word_for_everything_the_service_can_say():
    """A sixth strategy or a new availability would otherwise reach the screen in English."""
    assert {one.value for one in Availability} <= set(desk.STOCK)
    assert {one.value for one in Strategy} <= set(desk.CHOSEN)
    assert set(SPEC_TYPES) <= set(desk.SPECS)


def test_an_answer_renders_with_its_tools_and_a_refusal_renders_as_one(monkeypatch):
    """The chat is built from keys the API chooses, and a refusal is an answer like any other."""
    replies = iter(
        [
            {
                "conversation_id": 3,
                "answer": "Το PSU-1018 έχει 25 τεμάχια.",
                "refused": False,
                "tools": [{"name": "product_stock", "arguments": {"sku": "PSU-1018"}}],
                "rounds": 2,
            },
            {
                "conversation_id": 3,
                "answer": "Δεν μπορώ να τεκμηριώσω αυτή την απάντηση.",
                "refused": True,
                "tools": [{"name": "search_policies", "arguments": {"question": "εγγύηση"}}],
                "rounds": 3,
            },
        ]
    )
    monkeypatch.setattr(httpx, "post", lambda *_, **__: httpx.Response(200, json=next(replies)))
    monkeypatch.setattr(httpx, "get", lambda *_, **__: httpx.Response(200, json=[]))

    shown, thread, box, _ = desk.send("Τι απόθεμα έχει το PSU-1018;", None, "token", [])
    shown, thread, box, _ = desk.send("Και τι εγγύηση έχει;", thread, "token", shown)

    assert thread == 3
    assert box == ""
    assert [turn["role"] for turn in shown] == ["user", "assistant", "user", "assistant"]
    assert shown[1]["content"] == "Το PSU-1018 έχει 25 τεμάχια.\n\n*Από: product_stock*"
    assert (
        shown[3]["content"]
        == "Δεν μπορώ να τεκμηριώσω αυτή την απάντηση.\n\n*Από: search_policies*"
    )
