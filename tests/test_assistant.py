import json

import pytest

from services.offer_service.assistant import graph as assistant
from services.offer_service.assistant import grounding, model, tools
from services.offer_service.clients import catalog
from services.offer_service.rag import retriever
from services.offer_service.rag.retriever import Excerpt

QUESTION = "Τι απόθεμα έχει το PSU-1018;"
HELD = {"sku": "PSU-1018", "total": 12, "entries": [{"warehouse": "ATH-01", "quantity": 12}]}


def wants(name: str, **arguments) -> dict:
    """A reply that asks for one tool instead of answering."""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def says(text: str) -> dict:
    return {"role": "assistant", "content": text}


def wire(monkeypatch, *replies):
    """A model that gives these replies in turn, the last one for ever, and keeps what it saw."""
    given, seen = list(replies), []

    def complete(messages: list[dict]) -> dict:
        seen.append(list(messages))
        return given.pop(0) if len(given) > 1 else given[0]

    monkeypatch.setattr(model, "complete", complete)
    monkeypatch.setattr(catalog, "stock", lambda sku: HELD if sku == "PSU-1018" else None)
    return seen


def run(question: str = QUESTION):
    return assistant.build_graph().invoke(assistant.make_initial_state(question, []))


def test_the_tool_the_model_asked_for_runs_and_its_result_goes_back_to_it(monkeypatch):
    seen = wire(
        monkeypatch,
        wants("product_stock", sku="PSU-1018"),
        says("Το PSU-1018 έχει 12 τεμάχια στην ATH-01."),
    )

    state = run()
    fed = seen[1][-1]

    assert fed["role"] == "tool" and fed["tool_call_id"] == "call_1"
    assert json.loads(fed["content"])["total"] == 12
    assert state["answer"] == "Το PSU-1018 έχει 12 τεμάχια στην ATH-01."
    assert state["tools_used"] == [{"name": "product_stock", "arguments": {"sku": "PSU-1018"}}]
    assert state["refused"] is None


def test_a_code_no_tool_returned_is_sent_back_once_and_then_refused(monkeypatch):
    seen = wire(
        monkeypatch,
        wants("product_stock", sku="PSU-1018"),
        says("Το PSU-9999 έχει 12 τεμάχια."),
    )

    state = run()

    assert len(seen) == 3
    assert "PSU-9999" in json.loads(seen[2][-1]["content"])["fix"]
    assert state["answer"] is None
    assert "PSU-9999" in state["refused"]
    assert state["rounds"] == 3


def test_a_model_that_never_stops_asking_is_stopped_at_the_cap(monkeypatch):
    seen = wire(monkeypatch, wants("product_stock", sku="PSU-1018"))

    with pytest.raises(assistant.AssistantFailed):
        run()

    assert len(seen) == assistant.MAX_ROUNDS


def test_a_tool_that_does_not_exist_is_answered_to_the_model_not_raised(monkeypatch):
    seen = wire(monkeypatch, wants("price_list", category="UPS"), says("Δεν έχω τιμοκατάλογο."))

    state = run("Δώσε μου τον τιμοκατάλογο.")

    assert "no tool called price_list" in json.loads(seen[1][-1]["content"])["error"]
    assert state["answer"] == "Δεν έχω τιμοκατάλογο."


def test_a_figure_written_in_greek_is_the_figure_the_tool_wrote_in_json():
    evidence = [json.dumps({"sku": "UPS-1005", "price": 1261.57, "stock_total": 3})]

    assert grounding.unsupported("Το UPS-1005 κάνει 1.261,57 € και έχει 3.", evidence, "") == []
    assert grounding.unsupported("Το UPS-1005 κάνει 1.262 €.", evidence, "") == ["1.262"]


def test_an_earlier_turn_lends_its_code_to_the_answer_but_never_its_figures():
    earlier = ["Τι απόθεμα έχει το UPS-1021;", "Το UPS-1021 έχει 80 τεμάχια στην ATH-02."]
    evidence = [json.dumps({"section": "Εγγύηση ανά κατηγορία", "text": "UPS | 2 έτη"})]

    assert grounding.unsupported("Το UPS-1021 έχει εγγύηση 2 έτη.", evidence, "", earlier) == []
    assert grounding.unsupported("Το UPS-1021 έχει 80 τεμάχια.", evidence, "", earlier) == ["80"]
    assert (
        grounding.unsupported("Κάτω από 300 € δεν έχουμε UPS.", ["{}"], "UPS κάτω από 300 €") == []
    )


def test_numbering_a_list_is_not_a_claim_the_answer_has_to_support():
    """An answer written as 1. 2. 3. carries numbers no tool returned, and none of them is said."""
    evidence = [json.dumps({"sku": "UPS-1021", "price": 1261.57, "stock_total": 3})]
    answer = "1. Το UPS-1021 κάνει 1.261,57 €.\n2. Έχουμε 3 τεμάχια.\n4. Παράδοση αυθημερόν."

    assert grounding.unsupported(answer, evidence, "") == []


def test_a_datasheet_comes_back_only_for_a_product_the_conversation_is_about(monkeypatch):
    """Every warranty question reaches a datasheet; only the subject's one is about it."""
    found = [
        Excerpt(id="1", text="UPS | 2 έτη", metadata={"kind": "policy", "section": "Εγγύηση"}),
        Excerpt(id="2", text="…", metadata={"kind": "datasheet", "sku": "UPS-1014"}),
        Excerpt(id="3", text="…", metadata={"kind": "datasheet", "sku": "UPS-1021"}),
    ]
    monkeypatch.setattr(retriever, "search_policies", lambda question, limit=None: (found, {}))

    about_1021 = tools.search_policies("τι εγγύηση έχει;", ("UPS-1021",))
    about_nothing = tools.search_policies("πότε παραδίδουμε αυθημερόν;")

    assert [one["document"] for one in about_1021] == [None, None]
    assert [one["section"] for one in about_1021] == ["Εγγύηση", None]
    assert len(about_nothing) == 1
