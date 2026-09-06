import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.data_service.database import get_db
from services.data_service.generation import service
from services.data_service.main import app
from services.data_service.models import Supplier, TableBase

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

LINE = "Καλώδιο ρεύματος 3x2.5mm 20m 1500W IP44 εξωτερικού χώρου"
SHOP = "Καλώδιο Elektra 3x2.5mm σε μήκος 20m, με IP44 και αντοχή 1500W, για υπαίθριες παροχές."


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


client = TestClient(app)


def upload(*rows: dict) -> dict:
    """Write the rows out as the CSV somebody would have filled in, and send it."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=service.IMPORT_COLUMNS)
    writer.writeheader()

    for row in rows:
        writer.writerow(
            {
                "description": LINE,
                "web_description": SHOP,
                "cat": "POWER",
                "brand": "Elektra",
                "unit": "ΤΕΜ",
                "supplier": "SUP-01",
                "currency": "EUR",
                "updated_at": "2026-09-01",
                "qty_available": "40",
                "warehouse": "ATH-01",
                **row,
            }
        )

    return client.post(
        "/admin/import",
        files={"file": ("feed.csv", buffer.getvalue().encode("utf-8"), "text/csv")},
    ).json()


def test_the_template_has_the_columns_and_nothing_else():
    body = client.get("/admin/import/template").text

    assert body.strip().split(",") == service.IMPORT_COLUMNS
    assert body.count("\n") == 1


def test_a_price_the_shop_wrote_its_own_way_still_reads():
    report = upload({"item_code": "  pwr1500", "list_price": "€ 134,20"})
    found = client.post("/products/lookup", json={"skus": ["PWR-1500"]}).json()

    assert report["products_loaded"] == 1
    assert found[0]["price"] == 134.20
    assert found[0]["web_description"] == SHOP


def test_a_line_with_no_price_still_becomes_a_product():
    upload({"item_code": "PWR-1501", "list_price": "N/A"})
    found = client.post("/products/lookup", json={"skus": ["PWR-1501"]}).json()

    assert found[0]["price"] is None
    assert found[0]["specs"]["watt"] == 1500


def test_a_bad_line_is_reported_once_not_once_per_column_group():
    report = upload({"item_code": "", "list_price": "10.00"})

    assert report["products_loaded"] == 0
    assert report["rejected_by_reason"] == {"unreadable SKU": 1}


def test_a_file_saved_by_a_greek_excel_reads_the_same():
    """Windows-1253, semicolons, and a date left as the serial number Excel writes."""
    body = io.StringIO()
    writer = csv.DictWriter(
        body, fieldnames=service.IMPORT_COLUMNS, delimiter=";", lineterminator="\r\n"
    )
    writer.writeheader()
    writer.writerow(
        {
            "item_code": "PWR-1503",
            "description": LINE,
            "web_description": SHOP,
            "cat": "POWER",
            "brand": "Elektra",
            "unit": "ΤΕΜ",
            "supplier": "SUP-01",
            "list_price": "134,20 EUR",
            "currency": "EUR",
            "updated_at": "46266",
            "qty_available": "5",
            "warehouse": "ATH-01",
        }
    )

    report = client.post(
        "/admin/import",
        files={"file": ("excel.csv", body.getvalue().encode("cp1253"), "text/csv")},
    ).json()
    found = client.post("/products/lookup", json={"skus": ["PWR-1503"]}).json()

    assert report["products_loaded"] == 1
    assert found[0]["price"] == 134.20
    assert found[0]["price_updated_at"] == "2026-09-01"


def test_an_import_can_be_taken_back_out():
    report = upload({"item_code": "PWR-1502", "list_price": "55.00"})
    before = client.get("/stats").json()["products"]

    client.delete(f"/admin/runs/{report['request_id']}")

    assert client.get("/stats").json()["products"] == before - 1
