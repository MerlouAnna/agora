import random

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.data_service.categories import Category, specs_for
from services.data_service.database import get_db
from services.data_service.generation import builder, descriptions
from services.data_service.ingestion.parsers import extract_specs
from services.data_service.main import app
from services.data_service.models import Supplier, TableBase

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module", autouse=True)
def catalogue():
    TableBase.metadata.create_all(bind=engine)
    db = TestingSession()
    db.add(
        Supplier(code="SUP-01", name="Ionia Electric", lead_time_days=3, reliability_score=0.96)
    )
    db.commit()
    db.close()

    app.dependency_overrides[get_db] = lambda: TestingSession()
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def phrasing(monkeypatch):
    """Stand in for the model with a line the validator accepts."""
    monkeypatch.setattr(
        descriptions,
        "_ask_model",
        lambda requests: {r["sku"]: f"{r['erp']}, {r['brand']}" for r in requests},
    )


client = TestClient(app)


def test_every_spec_survives_the_description():
    """Whatever the builder chose has to be readable back out of the text it wrote."""
    rng = random.Random(1)

    for category in Category:
        specs = builder.build_specs(category, rng)
        found = extract_specs(category, builder.describe(category, specs, rng))
        assert set(found) == set(specs_for(category)), category


def test_the_same_seed_builds_the_same_products():
    runs = []
    for _ in range(2):
        report = client.post("/admin/generate", json={"count": 5, "seed": 88}).json()
        products = client.post("/products/lookup", json={"skus": report["skus"]}).json()
        runs.append([(p["description"], p["price"]) for p in products])

    assert runs[0] == runs[1]


def test_a_pinned_run_stays_inside_its_band():
    report = client.post(
        "/admin/generate",
        json={"count": 5, "seed": 3, "category": "PSU", "price_min": 60, "price_max": 65},
    ).json()

    products = client.post("/products/lookup", json={"skus": report["skus"]}).json()
    assert {p["category"] for p in products} == {"PSU"}
    assert all(60 <= p["price"] <= 65 for p in products)


def test_the_report_matches_what_the_catalogue_gained():
    report = client.post("/admin/generate", json={"count": 4, "seed": 11}).json()

    assert report["products_after"] - report["products_before"] == report["products_added"]
    assert client.get("/stats").json()["products"] == report["products_after"]


def test_a_run_can_be_taken_back_out():
    before = client.get("/stats").json()["products"]
    report = client.post("/admin/generate", json={"count": 3, "seed": 55}).json()
    removal = client.delete(f"/admin/runs/{report['request_id']}").json()

    assert removal["products_removed"] == report["products_added"]
    assert client.get("/stats").json()["products"] == before
    assert client.delete(f"/admin/runs/{report['request_id']}").status_code == 404


def test_a_product_the_model_cannot_phrase_is_left_out(monkeypatch):
    monkeypatch.setattr(descriptions, "_ask_model", lambda requests: {})

    report = client.post("/admin/generate", json={"count": 3, "seed": 77}).json()

    assert report["products_added"] == 0
    assert report["descriptions_rejected"] == 3
    assert report["rounds"] == descriptions.MAX_ROUNDS


def test_the_rebuild_loads_the_source_files_into_this_catalogue():
    report = client.post("/admin/rebuild").json()

    assert client.get("/stats").json()["products"] == report["products_loaded"]
    assert client.get("/admin/runs").json() == []
