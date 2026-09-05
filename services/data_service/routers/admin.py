"""
Admin routes
============
Growing the catalogue on demand, taking a batch back out, and rebuilding the whole thing
from the source files.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session
from starlette import status

from services.data_service.database import get_db
from services.data_service.generation import service
from services.data_service.ingestion import pipeline
from services.data_service.schemas import (
    GenerationRemoval,
    GenerationReport,
    GenerationRequest,
    GenerationRunSummary,
    LoadReport,
)

router = APIRouter()

db_dependency = Annotated[Session, Depends(get_db)]


@router.post(
    "/generate",
    response_model=GenerationReport,
    summary="Add products to the catalogue",
    response_description="What the run added, and how large the catalogue is now",
)
async def generate_products(db: db_dependency, request: GenerationRequest):
    """
    Builds new products and loads them into the live catalogue.

    Everything is drawn from the category registry, so a product cannot be invented for a
    category the rest of the system has never heard of: pick one from the list and its
    specifications, its price band and its SKU prefix follow. Leave `category` empty and
    the products are spread over all six.

    The rows are then written out the way the ERP, the pricing export and the warehouse
    system write them, and read back through the same normalizer the file ingestion uses.
    A record that cannot survive that trip is counted in `rejected` rather than stored.

    Every run keeps its `seed`. Pass a previous seed back with the same parameters and the
    same products come out — which is what makes a generated catalogue worth trusting.
    """
    return service.generate(db, request)


@router.get(
    "/runs",
    response_model=list[GenerationRunSummary],
    summary="Previous generation runs",
    response_description="The most recent runs, newest first",
)
async def read_runs(
    db: db_dependency,
    limit: int = Query(20, ge=1, le=100, description="How many runs to return."),
):
    """
    Every generation run the catalogue has been through, with the parameters it was given,
    the seed it used and the SKUs it produced.
    """
    return service.history(db, limit)


@router.delete(
    "/runs/{request_id}",
    response_model=GenerationRemoval,
    summary="Take a generation run back out",
    response_description="What was removed, and how large the catalogue is now",
)
async def delete_run(
    db: db_dependency,
    request_id: int = Path(ge=1, description="The run to undo."),
):
    """
    Removes every product one run added, together with its specifications, its stock rows
    and its price, and drops the run from the log. Nothing else in the catalogue is
    touched — a run only ever knows the SKUs it produced itself.

    A run whose products are already gone, because the catalogue was rebuilt from the
    source files in the meantime, is not an error: those SKUs come back under
    `already_gone` and the run is dropped anyway.
    """
    removal = service.remove(db, request_id)

    if removal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Generation run not found"
        )

    return removal


@router.post(
    "/rebuild",
    response_model=LoadReport,
    summary="Rebuild the catalogue from the source files",
    response_description="What the four files put back, and what they could not",
)
async def rebuild_catalogue(db: db_dependency):
    """
    Empties the catalogue and loads it again from `data/raw/` — the ERP export, the
    warehouse stock file, the pricing export and the supplier registry.

    **Everything added through `/admin/generate` is discarded**, the generation log
    included, and the catalogue comes back exactly as the four files describe it: the same
    products, the same specifications, the same prices, every time. This is the reset, not
    a refresh — there is nothing here that merges new rows into what is already stored.

    The report says how many rows each file offered and how many survived. A row that was
    left out is counted under `rejected_by_reason`, which is where an unreadable SKU or a
    price the source wrote as `N/A` shows up.
    """
    return pipeline.run(db)
