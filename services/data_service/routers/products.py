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
def search_products(
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
    offset: int = Query(
        0, ge=0, description="How many matches to skip. Use it to read the catalogue in pages."
    ),
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

    The whole catalogue, a hundred at a time:

        /products/search?limit=100&offset=0 … &offset=100 … until a page comes back short
    """
    products = repository.search_products(
        db,
        category=category.value if category else None,
        min_watt=min_watt,
        min_length_m=min_length_m,
        max_price=max_price,
        min_stock=min_stock,
        limit=limit,
        offset=offset,
    )
    return repository.summarize(db, products)


@router.post(
    "/lookup",
    response_model=list[ProductSummary],
    summary="Look up several products at once",
)
def lookup_products(db: db_dependency, request: LookupRequest):
    """Read several products at once, or one — pass a single SKU.

    This is what the offer service calls once semantic search has produced candidate
    SKUs: one request instead of one per product. SKUs are cleaned before the lookup, so
    `pwr1007` and `PWR-1007` find the same product.
    """
    wanted = [parsers.normalize_sku(sku) for sku in request.skus]
    return repository.summarize(db, repository.get_products(db, [sku for sku in wanted if sku]))


@router.get(
    "/{sku}/stock",
    response_model=ProductStock,
    summary="Where a product is held, and how much of it",
)
def read_stock(db: db_dependency, sku: str = Path(min_length=3)):
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
