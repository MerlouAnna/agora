"""
Normalizer
==========
Whatever arrives becomes one canonical record. There are two ways in.

`normalize_catalog` takes the structured catalogue, where the values already have types and
the work is validation and pulling the specifications out of the ERP line.

`normalize_products` and `normalize_stock` take rows that were exported by something else —
the generation endpoint, a partner's CSV — where the column names differ, the prices are
written three ways and the SKUs have been typed by hand. Every value goes through the
parsers, and whatever cannot be salvaged comes back as a rejection instead of stopping the
run.
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
    "web_description": "web_description",
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
    web_description: str | None = None
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


# ── The catalogue ─────────────────────────────────────────────────────────────


def normalize_catalog(
    products: list[dict],
) -> tuple[list[CanonicalProduct], list[CanonicalStock], list[Rejection]]:
    """Turn the structured catalogue into canonical products and their stock entries.

    Args:
        products: One record per SKU, as the catalogue file holds them.

    Returns:
        The products, their stock entries, and whatever could not be read. A record that
        fails is left out; the rest of the catalogue still loads.
    """
    canonical: dict[str, CanonicalProduct] = {}
    entries: list[CanonicalStock] = []
    rejections: list[Rejection] = []

    for record in products:
        raw_sku = str(record.get("sku", ""))
        sku = parsers.normalize_sku(raw_sku)

        if sku is None:
            rejections.append(Rejection("catalog", raw_sku.strip(), "unreadable SKU"))
            continue
        if sku in canonical:
            rejections.append(Rejection("catalog", sku, "duplicate SKU"))
            continue

        try:
            category = Category(record["category"])
            product = CanonicalProduct(
                sku=sku,
                category=category,
                brand=record["brand"],
                description=record["description"].strip(),
                web_description=(record.get("web_description") or "").strip() or None,
                unit=record.get("unit", "ΤΕΜ"),
                specs=parsers.extract_specs(category, record["description"]),
                supplier_code=record.get("supplier"),
                price=record.get("price"),
                currency=record.get("currency", "EUR"),
                price_updated_at=parsers.parse_date(record.get("price_updated_at", "")),
            )
        except (ValidationError, ValueError, KeyError) as exc:
            rejections.append(Rejection("catalog", sku, _first_problem(exc)))
            continue

        canonical[sku] = product

        for held in record.get("stock", []):
            try:
                entries.append(CanonicalStock(sku=sku, **held))
            except (ValidationError, TypeError) as exc:
                rejections.append(Rejection("catalog", sku, _first_problem(exc)))

    return list(canonical.values()), entries, rejections


# ── Exported rows ─────────────────────────────────────────────────────────────


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
        shop_text = (row.get(ERP_FIELDS["web_description"]) or "").strip()
        price = prices.get(sku, {})

        try:
            product = CanonicalProduct(
                sku=sku,
                category=row[ERP_FIELDS["category"]].strip(),
                brand=row[ERP_FIELDS["brand"]].strip(),
                description=description,
                web_description=shop_text or None,
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
    if isinstance(exc, KeyError):
        return f"missing field {exc}"
    return str(exc)
