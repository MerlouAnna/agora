import pytest
from fastapi.testclient import TestClient

from services import security
from services.config import settings
from services.offer_service.clients import history
from services.offer_service.main import app
from services.offer_service.routers import assistant as route

client = TestClient(app)

QUESTION = "Τι απόθεμα έχει το PSU-1018;"
TOOLS = [{"name": "product_stock", "arguments": {"sku": "PSU-1018"}}]
THREAD = {
    "id": 7,
    "username": "pmoschos",
    "started_at": "2026-09-13T10:00:00",
    "messages": [
        {
            "id": 1,
            "role": "user",
            "content": "γεια",
            "tools": None,
            "created_at": "2026-09-13T10:00:01",
        }
    ],
}


@pytest.fixture(autouse=True)
def logged_in(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", "test-only")
    client.headers["Authorization"] = f"Bearer {security.create_access_token('pmoschos')}"


def wire(monkeypatch, answer="12 τεμάχια στην ATH-01.", refused=None):
    """The history and the graph replaced; what gets recorded is handed back."""
    recorded = []

    def conversation(conversation_id: int, username: str) -> dict:
        if conversation_id != THREAD["id"]:
            raise history.ConversationNotFound(f"conversation {conversation_id} is not theirs")
        return THREAD

    def add_message(conversation_id, username, role, content, tools=None) -> dict:
        recorded.append((username, role, content, tools))
        return {}

    class Graph:
        def invoke(self, state: dict) -> dict:
            return state | {"answer": answer, "refused": refused, "tools_used": TOOLS, "rounds": 2}

    monkeypatch.setattr(history, "conversation", conversation)
    monkeypatch.setattr(history, "add_message", add_message)
    monkeypatch.setattr(route, "graph", lambda: Graph())
    return recorded


def test_both_turns_are_recorded_under_the_user_the_token_names(monkeypatch):
    recorded = wire(monkeypatch)

    answered = client.post("/assistant/ask", json={"question": QUESTION, "conversation_id": 7})
    body = answered.json()

    assert answered.status_code == 200
    assert body["conversation_id"] == 7
    assert body["answer"] == "12 τεμάχια στην ATH-01."
    assert body["refused"] is False
    assert recorded == [
        ("pmoschos", "user", QUESTION, None),
        ("pmoschos", "assistant", "12 τεμάχια στην ATH-01.", TOOLS),
    ]


def test_a_conversation_that_is_not_the_users_is_404_and_nothing_is_recorded(monkeypatch):
    recorded = wire(monkeypatch)

    answered = client.post("/assistant/ask", json={"question": QUESTION, "conversation_id": 8})

    assert answered.status_code == 404
    assert recorded == []


def test_the_conversation_list_is_asked_for_under_the_token_user_only(monkeypatch):
    asked_for = []
    monkeypatch.setattr(history, "conversations", lambda username: asked_for.append(username) or [])

    answered = client.get("/assistant/conversations")

    assert answered.status_code == 200
    assert answered.json() == []
    assert asked_for == ["pmoschos"]
