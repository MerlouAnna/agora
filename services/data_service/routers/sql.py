"""
SQL routes
==========
The schema of the catalogue, and a read-only console over it.
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette import status

from services.data_service import console
from services.data_service.database import get_db
from services.data_service.schemas import CatalogueSchema, QueryRequest, QueryResult

router = APIRouter()

db_dependency = Annotated[Session, Depends(get_db)]


@router.get(
    "/schema",
    response_model=CatalogueSchema,
    summary="What there is to query",
    response_description="Every table with its columns, keys and row count",
)
async def read_schema():
    """
    The shape of the catalogue as the database holds it: the tables, their columns and
    types, which column is the key, which columns point at which other table, and how many
    rows each holds right now.

    The specifications are worth a word. They are not columns. `product_specs` holds one
    row per specification — `sku`, `key`, and the value in `value_num` when it is a number
    and `value_text` when it is a label — so a query filtering on two specifications joins
    that table twice. The examples below show it.
    """
    return CatalogueSchema(tables=console.tables(), examples=console.EXAMPLES)


@router.post(
    "/query",
    response_model=QueryResult,
    summary="Run a SELECT against the catalogue",
    response_description="The columns and rows the statement returned",
)
async def run_query(request: QueryRequest):
    """
    Runs one statement and hands back what it found.

    Only a single `SELECT` is accepted, or a `WITH` that ends in one. The statement is read
    before it runs, and then it runs on a connection SQLite opened **read-only** — so even a
    statement that gets past the reader cannot change anything. A query that takes longer
    than five seconds is stopped.

    The statement itself is never rewritten. The `limit` decides how many rows are read
    back, and `truncated` says whether there were more.
    """
    try:
        return QueryResult(**console.run(request.sql, request.limit))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"SQLite: {exc}"
        ) from exc
