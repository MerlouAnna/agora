import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.data_service.database import get_db
from services.data_service.main import app
from services.data_service.models import Price, Product, ProductSpec, Stock, TableBase

# One shared connection, otherwise the test client's thread opens its own empty database.
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

    db.add(Product(sku="PWR-1001", category="POWER", brand="Kyma", description="…", unit="ΤΕΜ"))
    db.add(Product(sku="PWR-1002", category="POWER", brand="Kyma", description="…", unit="ΤΕΜ"))
    db.add_all(
        [
            ProductSpec(sku="PWR-1001", key="watt", value_num=1500),
            ProductSpec(sku="PWR-1002", key="watt", value_num=750),
            Price(sku="PWR-1001", amount=96.20, currency="EUR"),
            Stock(sku="PWR-1001", warehouse="ATH-01", quantity=12),
            Stock(sku="PWR-1001", warehouse="THE-01", quantity=8),
        ]
    )
    db.commit()
    db.close()

    app.dependency_overrides[get_db] = lambda: TestingSession()
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


def test_search_applies_the_spec_minimum():
    found = client.get("/products/search", params={"min_watt": 1000}).json()
    assert [p["sku"] for p in found] == ["PWR-1001"]


def test_unknown_sku_is_404():
    assert client.get("/products/NOPE-9999/stock").status_code == 404


def test_stock_totals_the_warehouses():
    body = client.get("/products/PWR-1001/stock").json()
    assert body["total"] == 20
    assert len(body["entries"]) == 2


def test_a_product_with_no_stock_record_reports_null():
    found = client.post("/products/lookup", json={"skus": ["PWR-1002"]}).json()
    assert found[0]["stock_total"] is None


def test_stats_add_up():
    body = client.get("/stats").json()
    assert sum(row["products"] for row in body["by_category"]) == body["products"]
    assert body["without_stock_record"] == 1
