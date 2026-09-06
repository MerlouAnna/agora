"""
Catalogue statistics
====================
One request that says what is in the database at this moment.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from services.data_service import repository
from services.data_service.database import get_db
from services.data_service.schemas import (
    CatalogueStats,
    CategoryStats,
    SupplierStats,
    WarehouseStats,
)

router = APIRouter()

db_dependency = Annotated[Session, Depends(get_db)]


@router.get(
    "",
    response_model=CatalogueStats,
    summary="What is in the catalogue right now",
    response_description="Totals, a breakdown per category, warehouse and supplier, and the gaps",
)
def read_stats(db: db_dependency):
    """
    A single overview of the catalogue as it currently stands: how many products and
    specifications are stored, how many units sit in each warehouse and what they are
    worth, and how the products divide across categories and suppliers.

    The three gap counts are worth reading together. `without_stock_record` are products
    the warehouse system has no row for — their stock is unknown. `out_of_stock` are
    products it does have a row for, saying zero. `without_price` cannot be quoted at all.
    """
    units, value = repository.stock_totals(db)
    without_stock, without_price, out_of_stock = repository.gaps(db)

    return CatalogueStats(
        products=repository.count_products(db),
        specs=repository.count_specs(db),
        stock_units=units,
        stock_value=value,
        without_stock_record=without_stock,
        without_price=without_price,
        out_of_stock=out_of_stock,
        by_category=[
            CategoryStats(
                category=category,
                products=count,
                min_price=lowest,
                max_price=highest,
                avg_price=round(average, 2) if average is not None else None,
            )
            for category, count, lowest, highest, average in repository.by_category(db)
        ],
        by_warehouse=[
            WarehouseStats(warehouse=warehouse, skus=skus, units=units)
            for warehouse, skus, units in repository.by_warehouse(db)
        ],
        by_supplier=[
            SupplierStats(
                code=code,
                name=name,
                lead_time_days=lead_time,
                reliability_score=reliability,
                products=count,
            )
            for code, name, lead_time, reliability, count in repository.by_supplier(db)
        ],
    )
