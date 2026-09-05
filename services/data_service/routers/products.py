"""
Product routes
==============
Search, single lookup, stock, and a batch lookup for the offer service.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session
from starlette import status

from services.data_service import repository
from services.data_service.categories import Category
from services.data_service.database import get_db
from services.data_service.ingestion import parsers
from services.data_service.models import Product
from services.data_service.schemas import (
    LookupRequest,
    ProductStock,
    ProductSummary,
    StockEntry,
)

router = APIRouter()

db_dependency = Annotated[Session, Depends(get_db)]


@router.get(
    "/search",
    response_model=list[ProductSummary],
    summary="Search the catalogue",
    response_description="Matching products with their specs, price and availability",
)
async def search_products(
    db: db_dependency,
    category: Category | None = Query(
        None, description="Restrict to one category. Leave empty to search all six."
    ),
    min_watt: float | None = Query(
        None,
        ge=0,
        description="Lowest acceptable wattage. Cables, power supplies, UPS units.",
    ),
    min_length_m: float | None = Query(
        None, ge=0, description="Lowest acceptable length in metres. Cables only."
    ),
    max_price: float | None = Query(
        None, gt=0, description="Highest acceptable list price, in euro."
    ),
    min_stock: int | None = Query(
        None,
        ge=0,
        description=(
            "Lowest acceptable quantity across all warehouses. Products whose stock is "
            "unknown are left out when this is set."
        ),
    ),
    limit: int = Query(20, ge=1, le=100, description="How many products to return."),
):
    """
    Find products by category, technical minimums, price ceiling and availability.

    Every filter you give is applied **together**; a filter you leave empty is not applied
    at all. A search with no filters returns the first products in the catalogue.

    The technical minimums are matched against each product's stored specifications, not
    against its description text. The specifications were extracted during ingestion, so
    `min_watt=1000` finds both a cable written up as *1000W* and one written up as *1kW*.

    `stock_total` comes back as `null` when the warehouse system holds no record for that
    product. That is not the same as zero — it means unknown, not out of stock.

    A cable for a 1000 W load, at least 20 metres, under €120, with at least 5 in stock:

        /products/search?category=POWER&min_watt=1000&min_length_m=20&max_price=120&min_stock=5
    """
    products = repository.search_products(
        db,
        category=category.value if category else None,
        min_watt=min_watt,
        min_length_m=min_length_m,
        max_price=max_price,
        min_stock=min_stock,
        limit=limit,
    )
    return _summarize(db, products)


@router.post(
    "/lookup",
    response_model=list[ProductSummary],
    summary="Look up several products at once",
)
async def lookup_products(db: db_dependency, request: LookupRequest):
    """Read several products at once, or one — pass a single SKU.

    This is what the offer service calls once semantic search has produced candidate
    SKUs: one request instead of one per product. SKUs are cleaned before the lookup, so
    `pwr1007` and `PWR-1007` find the same product.
    """
    wanted = [parsers.normalize_sku(sku) for sku in request.skus]
    return _summarize(db, repository.get_products(db, [sku for sku in wanted if sku]))


@router.get(
    "/{sku}/stock",
    response_model=ProductStock,
    summary="Where a product is held, and how much of it",
)
async def read_stock(db: db_dependency, sku: str = Path(min_length=3)):
    """Quantity per warehouse. The SKU is cleaned first, so quotes and casing do not matter."""
    sku = parsers.normalize_sku(sku) or sku

    if repository.get_product(db, sku) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )

    entries = repository.get_stock(db, sku)
    total = sum(entry.quantity for entry in entries) if entries else None

    return ProductStock(
        sku=sku,
        total=total,
        entries=[
            StockEntry(warehouse=e.warehouse, quantity=e.quantity) for e in entries
        ],
    )


def _summarize(db: Session, products: list[Product]) -> list[ProductSummary]:
    """Attach specs, price and stock to each product in two extra queries, not two per row."""
    skus = [product.sku for product in products]
    specs = repository.get_specs(db, [str(sku) for sku in skus])
    totals = repository.get_stock_totals(db, [str(sku) for sku in skus])
    prices = repository.get_prices(db, [str(sku) for sku in skus])

    summaries = []
    for product in products:
        price = prices.get(str(product.sku))
        summaries.append(
            ProductSummary(
                sku=str(product.sku),
                category=str(product.category),
                brand=str(product.brand),
                description=str(product.description),
                web_description=product.web_description,
                unit=str(product.unit),
                supplier_code=product.supplier_code,
                price=float(price.amount) if price else None,
                currency=str(price.currency) if price else None,
                price_updated_at=price.updated_at if price else None,
                specs=specs.get(str(product.sku), {}),
                stock_total=totals.get(str(product.sku)),
            )
        )

    return summaries
