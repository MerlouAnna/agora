from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services import usage
from services.data_service.database import get_db
from services.data_service.main import app
from services.data_service.models import LlmCall, TableBase

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module", autouse=True)
def log():
    TableBase.metadata.create_all(bind=engine)
    db = TestingSession()

    db.add_all(
        [
            LlmCall(
                called_at=datetime(2026, 9, 5, 10),
                service="data_service",
                purpose="product-descriptions",
                model="gpt-4o-mini",
                prompt_tokens=10_000,
                completion_tokens=2_000,
                ok=True,
            ),
            LlmCall(
                called_at=datetime(2026, 9, 5, 11),
                service="offer_service",
                purpose="indexing",
                model="text-embedding-3-small",
                prompt_tokens=1_000_000,
                completion_tokens=0,
                ok=True,
            ),
            LlmCall(
                called_at=datetime(2026, 9, 5, 12),
                service="data_service",
                purpose="product-descriptions",
                model="gpt-4o-mini",
                ok=False,
                detail="rate limit",
            ),
        ]
    )
    db.commit()
    db.close()

    app.dependency_overrides[get_db] = lambda: TestingSession()
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


def test_a_model_with_no_price_on_file_costs_nothing():
    assert usage.cost("a-model-we-have-no-price-for", 1_000_000, 1_000_000) == 0.0


def test_each_model_is_priced_on_its_own_rate():
    body = client.get("/admin/usage").json()
    by_model = {line["label"]: line["estimated_cost_usd"] for line in body["by_model"]}

    assert body["calls"] == 3
    assert body["failed"] == 1
    assert by_model["gpt-4o-mini"] == pytest.approx(0.0027)
    assert by_model["text-embedding-3-small"] == pytest.approx(0.02)
    assert body["estimated_cost_usd"] == pytest.approx(0.0227)
