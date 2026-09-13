from urllib.parse import parse_qsl

import httpx
from fastapi.testclient import TestClient

from services.offer_service.clients import auth
from services.offer_service.main import app

client = TestClient(app)

ISSUED = {"access_token": "signed-by-the-data-service", "token_type": "bearer"}


def test_the_form_goes_through_and_the_token_comes_back_unchanged(monkeypatch):
    """A fake data service on the wire: what it was sent, and what it said, both pass through."""
    seen = []

    def data_service(request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        seen.append((request.url.path, form))
        if form["password"] == "ai-for-devs-moschos":
            return httpx.Response(200, json=ISSUED)
        return httpx.Response(401, json={"detail": "Incorrect username or password"})

    monkeypatch.setattr(
        auth,
        "_http",
        lambda: httpx.Client(base_url="http://data", transport=httpx.MockTransport(data_service)),
    )

    good = client.post(
        "/auth/login", data={"username": "pmoschos", "password": "ai-for-devs-moschos"}
    )
    bad = client.post("/auth/login", data={"username": "pmoschos", "password": "nope"})

    assert good.status_code == 200
    assert good.json() == ISSUED
    assert seen[0] == ("/auth/login", {"username": "pmoschos", "password": "ai-for-devs-moschos"})
    assert bad.status_code == 401
    assert bad.headers["WWW-Authenticate"] == "Bearer"
    assert bad.json()["detail"] == "Incorrect username or password"
