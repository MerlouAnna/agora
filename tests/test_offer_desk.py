from fastapi.testclient import TestClient

from services.data_service.categories import SPEC_TYPES
from services.offer_service.domain.models import Availability, Strategy
from services.offer_service.main import app
from tests.test_graph import BOTH, DEARER, REQUEST, wire
from ui import gradio_app as desk

client = TestClient(app)


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
