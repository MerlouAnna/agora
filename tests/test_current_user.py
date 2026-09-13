import pytest
from fastapi.testclient import TestClient
from jose import jwt

from services import security
from services.config import settings
from services.offer_service.main import app
from tests.test_graph import REQUEST

client = TestClient(app)


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", "test-only")


def test_no_token_is_401_before_anything_runs():
    answered = client.post("/offers/generate", json={"request": REQUEST})

    assert answered.status_code == 401
    assert answered.headers["WWW-Authenticate"] == "Bearer"


def test_a_token_signed_with_another_key_is_401():
    forged = jwt.encode({"sub": "pmoschos"}, "someone-elses-key", algorithm=security.ALGORITHM)

    answered = client.post(
        "/offers/generate",
        json={"request": REQUEST},
        headers={"Authorization": f"Bearer {forged}"},
    )

    assert answered.status_code == 401
