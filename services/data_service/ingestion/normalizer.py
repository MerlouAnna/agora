"""
Normalizer
==========
Four sources with four sets of column names become one canonical record. Every source
is read through its own field map, every value through the parsers, and whatever cannot
be salvaged is returned as a rejection instead of stopping the run.
"""

import logging
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, Field, ValidationError

from services.data_service.categories import Category, Warehouse
from services.data_service.ingestion import parsers

logger = logging.getLogger(__name__)

ERP_FIELDS = {
    "sku": "item_code",
    "description": "description",
    "category": "cat",
    "brand": "brand",
    "unit": "unit",
}
PRICING_FIELDS = {
    "sku": "product_code",
    "amount": "list_price",
    "currency": "currency",
    "updated_at": "updated_at",
}
STOCK_FIELDS = {"sku": "sku", "quantity": "qty_available", "warehouse": "warehouse"}


class CanonicalProduct(BaseModel):
    """What every source eventually agrees a product is."""

    sku: str
    category: Category
    brand: str
    description: str
    unit: str = "ΤΕΜ"
    specs: dict = Field(default_factory=dict)
    supplier_code: str | None = None
    price: float | None = Field(default=None, gt=0)
    currency: str = "EUR"
    price_updated_at: date | None = None


class CanonicalStock(BaseModel):
    sku: str
    warehouse: Warehouse
    quantity: int = Field(ge=0)


@dataclass
class Rejection:
    source: str
    identifier: str
    reason: str


# ── Products ──────────────────────────────────────────────────────────────────


def normalize_products(
    erp_rows: list[dict], pricing_rows: list[dict], suppliers: list[dict]
) -> tuple[list[CanonicalProduct], list[Rejection], int]:
    prices, rejections = _index_prices(pricing_rows)
    supplier_of = {
        sku: entry["supplier_code"] for entry in suppliers for sku in entry["supplies"]
    }

    products: dict[str, CanonicalProduct] = {}
    duplicates = 0

    for row in erp_rows:
        raw_sku = row[ERP_FIELDS["sku"]]
        sku = parsers.normalize_sku(raw_sku)
        if sku is None:
            rejections.append(Rejection("erp", raw_sku.strip(), "unreadable SKU"))
            continue

        if sku in products:
            duplicates += 1
            continue

        description = row[ERP_FIELDS["description"]].strip()
        price = prices.get(sku, {})

        try:
            product = CanonicalProduct(
                sku=sku,
                category=row[ERP_FIELDS["category"]].strip(),
                brand=row[ERP_FIELDS["brand"]].strip(),
                description=description,
                unit=row[ERP_FIELDS["unit"]].strip().upper(),
                specs=parsers.extract_specs(Category(row[ERP_FIELDS["category"]]), description),
                supplier_code=supplier_of.get(sku),
                **price,
            )
        except (ValidationError, ValueError) as exc:
            rejections.append(Rejection("erp", sku, _first_problem(exc)))
            continue

        products[sku] = product

    return list(products.values()), rejections, duplicates


def _index_prices(pricing_rows: list[dict]) -> tuple[dict[str, dict], list[Rejection]]:
    """Price rows keyed by SKU, so a product can be built in one pass.

    A product whose price cannot be used is still a product. The price is dropped and
    reported, and the product is loaded without one.
    """
    indexed = {}
    rejections = []

    for row in pricing_rows:
        raw_sku = row[PRICING_FIELDS["sku"]]
        sku = parsers.normalize_sku(raw_sku)
        if sku is None:
            rejections.append(Rejection("pricing", raw_sku.strip(), "unreadable SKU"))
            continue

        amount = parsers.parse_price(row[PRICING_FIELDS["amount"]])
        if amount is None:
            rejections.append(Rejection("pricing", sku, "unreadable price"))
            continue
        if amount <= 0:
            rejections.append(Rejection("pricing", sku, "price not above zero"))
            continue

        indexed[sku] = {
            "price": amount,
            "currency": row[PRICING_FIELDS["currency"]].strip(),
            "price_updated_at": parsers.parse_date(row[PRICING_FIELDS["updated_at"]]),
        }

    return indexed, rejections


# ── Stock ─────────────────────────────────────────────────────────────────────


def normalize_stock(
    stock_rows: list[dict], known_skus: set[str]
) -> tuple[list[CanonicalStock], list[Rejection]]:
    entries: dict[tuple[str, str], CanonicalStock] = {}
    rejections: list[Rejection] = []

    for row in stock_rows:
        raw_sku = row[STOCK_FIELDS["sku"]]
        sku = parsers.normalize_sku(raw_sku)
        quantity = parsers.parse_quantity(row[STOCK_FIELDS["quantity"]])

        if sku is None:
            rejections.append(Rejection("wms", raw_sku.strip(), "unreadable SKU"))
            continue
        if sku not in known_skus:
            rejections.append(Rejection("wms", sku, "no such product"))
            continue
        if quantity is None:
            rejections.append(Rejection("wms", sku, "unreadable quantity"))
            continue

        try:
            entry = CanonicalStock(
                sku=sku, warehouse=row[STOCK_FIELDS["warehouse"]].strip(), quantity=quantity
            )
        except ValidationError as exc:
            rejections.append(Rejection("wms", sku, _first_problem(exc)))
            continue

        entries[(entry.sku, entry.warehouse)] = entry

    return list(entries.values()), rejections


def _first_problem(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        error = exc.errors()[0]
        return f"{error['loc'][0]}: {error['msg']}"
    return str(exc)
