import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.data_service.database import get_db
from services.data_service.main import app
from services.data_service.models import TableBase

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module", autouse=True)
def history():
    TableBase.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = lambda: TestingSession()
    yield
    app.dependency_overrides.clear()


client = TestClient(app)

MARIA = {"username": "maria"}
NIKOS = {"username": "nikos"}
TOOLS = [{"name": "product_stock", "arguments": {"sku": "PSU-1018"}}]


def test_a_conversation_reads_back_in_the_order_it_was_written():
    opened = client.post("/conversations", json=MARIA)
    thread = opened.json()["id"]
    client.post(
        f"/conversations/{thread}/messages",
        params=MARIA,
        json={"role": "user", "content": "τι απόθεμα έχει το PSU-1018;"},
    )
    client.post(
        f"/conversations/{thread}/messages",
        params=MARIA,
        json={"role": "assistant", "content": "12 τεμάχια στην ATH-01.", "tools": TOOLS},
    )

    body = client.get(f"/conversations/{thread}", params=MARIA).json()
    listed = client.get("/conversations", params=MARIA).json()

    assert opened.status_code == 201
    assert [turn["role"] for turn in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["tools"] is None
    assert body["messages"][1]["tools"] == TOOLS
    assert [row["id"] for row in listed] == [thread]


def test_a_conversation_that_is_not_there_or_not_yours_is_404():
    thread = client.post("/conversations", json=MARIA).json()["id"]
    turn = {"role": "user", "content": "…"}

    assert client.get("/conversations/9999", params=MARIA).status_code == 404
    assert client.get(f"/conversations/{thread}", params=NIKOS).status_code == 404
    assert (
        client.post(f"/conversations/{thread}/messages", params=NIKOS, json=turn).status_code == 404
    )
