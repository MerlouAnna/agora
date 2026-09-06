"""
Admin routes
============
Growing the catalogue on demand, taking a batch back out, and rebuilding the whole thing
from the source files.
"""

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette import status

from services import usage
from services.data_service import repository
from services.data_service.database import get_db
from services.data_service.generation import descriptions, service
from services.data_service.ingestion import loader, pipeline
from services.data_service.models import LlmCall
from services.data_service.schemas import (
    GenerationRemoval,
    GenerationReport,
    GenerationRequest,
    GenerationRunSummary,
    LoadReport,
    UsageLine,
    UsageReport,
)

router = APIRouter()

db_dependency = Annotated[Session, Depends(get_db)]


@router.post(
    "/generate",
    response_model=GenerationReport,
    summary="Add products to the catalogue",
    response_description="What the run added, and how large the catalogue is now",
)
def generate_products(db: db_dependency, request: GenerationRequest):
    """
    Builds new products and loads them into the live catalogue.

    Everything is drawn from the category registry, so a product cannot be invented for a
    category the rest of the system has never heard of: pick one from the list and its
    specifications, its price band and its SKU prefix follow. Leave `category` empty and
    the products are spread over all six.

    The description is the one thing the code does not write. Each product's drafted line
    goes to the language model to be rewritten as a real catalogue entry, and what comes
    back is checked: every specification the code chose has to be readable out of the
    returned text, or the line goes back with the reason attached, up to three rounds. A
    product the model never gets right is **left out of the run** and counted in
    `descriptions_rejected` — a machine-written description would be a near-copy of one
    already in the catalogue, and the index this feeds cannot tell near-copies apart.
    A run can therefore add fewer products than were asked for.

    The rows are then written out the way the ERP, the pricing export and the warehouse
    system write them, and read back through the same normalizer the file ingestion uses.
    A record that cannot survive that trip is counted in `rejected` rather than stored.

    Every run keeps its `seed`. Pass a previous seed back with the same parameters and the
    same products come out, though the model phrases them afresh each time.

    Needs `OPENAI_API_KEY` in the environment; without one the request answers 503.
    """
    try:
        return service.generate(db, request)
    except descriptions.ModelUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.get(
    "/runs",
    response_model=list[GenerationRunSummary],
    summary="Previous generation runs",
    response_description="The most recent runs, newest first",
)
def read_runs(
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
def delete_run(
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
    response_description="What the file put back, and what it could not",
)
def rebuild_catalogue(db: db_dependency):
    """
    Empties the catalogue and loads it again from `data/raw/catalog.json` — the supplier
    registry and one record per SKU.

    **Everything added through `/admin/generate` is discarded**, the generation log
    included, and the catalogue comes back exactly as the file describes it: the same
    products, the same specifications, the same prices, every time. This is the reset, not
    a refresh — there is nothing here that merges new rows into what is already stored.

    The report says how many records the file offered and how many survived. A row that
    was left out is counted under `rejected_by_reason`, which is where an unreadable SKU
    or a supplier the registry has never heard of shows up. A price the source wrote as
    `N/A` is reported there too, but the product itself still loads — without one.
    """
    return pipeline.run(db)


@router.get(
    "/usage",
    response_model=UsageReport,
    summary="What the models have cost so far",
    response_description="Tokens and estimated spend, broken down by model, purpose and day",
)
def read_usage(
    db: db_dependency,
    days: int | None = Query(
        None, ge=1, le=365, description="Look only this far back. Leave empty for everything."
    ),
):
    """
    Every call to a language or embedding model is written down as it happens — which
    service made it, what it was for, which model answered, how many tokens each way and
    how long it took. This is the sum of that log.

    `by_purpose` is the one to read first: it says where the spend is going, and it will
    grow a line as each part of the system starts calling a model.

    `estimated_cost_usd` is arithmetic over the list prices recorded in
    `services/usage.py`, not anything the provider told us. Treat it as an order of
    magnitude, and check the numbers against the provider's own dashboard before quoting
    them anywhere that matters.
    """
    since = datetime.now() - timedelta(days=days) if days else None

    calls, failed, prompt, completion, first, last = repository.usage_totals(db, since)
    by_model = _lines(repository.usage_grouped(db, LlmCall.model, since))

    return UsageReport(
        calls=calls,
        failed=failed or 0,
        prompt_tokens=prompt or 0,
        completion_tokens=completion or 0,
        total_tokens=(prompt or 0) + (completion or 0),
        estimated_cost_usd=round(sum(line.estimated_cost_usd for line in by_model), 6),
        first_call=first,
        last_call=last,
        by_model=by_model,
        by_purpose=_lines(repository.usage_grouped(db, LlmCall.purpose, since)),
        by_day=_lines(
            repository.usage_grouped(db, func.date(LlmCall.called_at), since)
        ),
    )


def _lines(rows: list) -> list[UsageLine]:
    """Fold the per-model rows back into one line per label, pricing each model's share."""
    folded: dict[str, dict] = {}

    for label, model, calls, prompt, completion in rows:
        entry = folded.setdefault(
            str(label), {"calls": 0, "prompt": 0, "completion": 0, "cost": 0.0}
        )
        entry["calls"] += calls
        entry["prompt"] += prompt or 0
        entry["completion"] += completion or 0
        entry["cost"] += usage.cost(model, prompt or 0, completion or 0)

    return [
        UsageLine(
            label=label,
            calls=entry["calls"],
            prompt_tokens=entry["prompt"],
            completion_tokens=entry["completion"],
            estimated_cost_usd=round(entry["cost"], 6),
        )
        for label, entry in sorted(folded.items())
    ]


@router.get(
    "/import/template",
    response_class=PlainTextResponse,
    summary="Download the import template",
    response_description="A CSV with the column headings and no rows",
)
def import_template():
    """
    The file to fill in. One line per product, and the columns are the ones the reader
    knows: the code, the ERP line, the shop text, the category, the brand, the unit, the
    supplier, the price with its currency and date, and one warehouse with its quantity.

    Nothing here has to be tidy. The price may be written `€ 134,20`, `163.95` or
    `145,17 EUR`; the code may be `pwr1007`, `PWR 1003` or padded with spaces; a product
    with no warehouse line simply has unknown stock. That is what the reading is for.

    Save it however your spreadsheet saves it. The file is read as UTF-8, and failing that
    as Windows-1253 or Windows-1252, and the separator is taken from the heading line, so a
    semicolon file from a Greek Excel is read the same as a comma file. Dates come back
    whether they were written `2026-09-01`, `01/09/2026`, or as the serial number a
    spreadsheet leaves behind when the cell format is General.
    """
    return PlainTextResponse(
        service.template(),
        headers={"Content-Disposition": 'attachment; filename="agora-import.csv"'},
    )


@router.post(
    "/import",
    response_model=LoadReport,
    summary="Import a filled-in CSV",
    response_description="What the file put into the catalogue, and what it could not",
)
def import_products(db: db_dependency, file: UploadFile = File(...)):
    """
    Reads an uploaded CSV through exactly the checks the rest of the catalogue goes
    through: the codes are cleaned, the prices are read whichever way they were written,
    the categories and warehouses are matched against the registry, and the specifications
    are pulled out of the ERP line.

    A line that cannot be used is counted in `rejected_by_reason` rather than stopping the
    file, and a product whose price cannot be read still loads — without one. A SKU the
    catalogue already holds is left exactly as it is, and reported the same way.

    The import is recorded as a run, so `request_id` can be handed to
    `DELETE /admin/runs/{request_id}` to take the whole file back out again. One file
    carries at most 5000 lines; a larger catalogue goes in as several.
    """
    raw = file.file.read()

    try:
        rows = loader.read_upload(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="the file has no rows"
        )

    if len(rows) > service.MAX_IMPORT_ROWS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"the file has more than {service.MAX_IMPORT_ROWS} rows",
        )

    return service.import_rows(db, rows, file.filename or "upload.csv")
