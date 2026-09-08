"""
Suppliers
=========
The registry behind the products: who supplies what, how long they take, and how often
they deliver on it. The offer service needs the last two to date an out-of-stock order.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from services.data_service import repository
from services.data_service.database import get_db
from services.data_service.schemas import SupplierSummary

router = APIRouter()

db_dependency = Annotated[Session, Depends(get_db)]


@router.get(
    "",
    response_model=list[SupplierSummary],
    summary="Read the supplier registry",
    response_description="Every supplier with its lead time and reliability score",
)
def read_suppliers(db: db_dependency):
    """
    The four suppliers the catalogue buys from.

    `lead_time_days` is what the delivery terms count when a product is in no warehouse,
    and `reliability_score` is what decides whether a supplier can be committed to for an
    urgent order at all — anything below 0.80 cannot.
    """
    return [
        SupplierSummary(
            code=str(row.code),
            name=str(row.name),
            lead_time_days=int(row.lead_time_days),
            reliability_score=float(row.reliability_score),
        )
        for row in repository.get_suppliers(db)
    ]
