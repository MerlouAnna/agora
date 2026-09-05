"""
Generation service
==================
Adds products to a catalogue that is already running. The records are built here, then
written out in the shapes the ERP, the pricing export and the warehouse system use, and
read back through the same normalizer the file ingestion goes through — a generated
product is checked exactly the way an imported one is.

Every run is recorded with the seed it used, so the same catalogue can be produced again.
"""

import logging
import random
from collections import Counter, defaultdict
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from services.data_service import repository
from services.data_service.categories import SKU_PREFIXES, Category, Warehouse
from services.data_service.categories import SupplierCode
from services.data_service.generation import builder
from services.data_service.ingestion import normalizer
from services.data_service.ingestion.pipeline import spec_rows
from services.data_service.models import (
    GenerationRun,
    Price,
    Product,
    ProductSpec,
    Stock,
    Supplier,
)
from services.data_service.schemas import (
    GenerationRemoval,
    GenerationReport,
    GenerationRequest,
    GenerationRunSummary,
)

logger = logging.getLogger(__name__)


def generate(db: Session, request: GenerationRequest) -> GenerationReport:
    """Build the requested products, load them, and record what the run did.

    Args:
        db: Session on the catalogue the products are added to.
        request: How many products, and how far they are allowed to vary.

    Returns:
        The run as it was recorded, with the catalogue size before and after.
    """
    seed = request.seed if request.seed is not None else random.randrange(1, 10**9)
    rng = random.Random(seed)

    before = repository.count_products(db)
    drafts, exhausted = _draft(db, request, rng)

    erp_rows, pricing_rows, stock_rows = _raw_rows(drafts)
    products, rejections, _ = normalizer.normalize_products(
        erp_rows, pricing_rows, _supplier_entries(drafts)
    )
    stock, stock_rejections = normalizer.normalize_stock(
        stock_rows, {product.sku for product in products}
    )
    rejections = rejections + stock_rejections + _exhausted(exhausted)

    skus, specs_added, stock_added = _persist(db, products, stock)

    run = GenerationRun(
        created_at=datetime.now(),
        seed=seed,
        requested=request.count,
        products_added=len(skus),
        specs_added=specs_added,
        stock_rows_added=stock_added,
        rejected=len(rejections),
        rounds=1,
        descriptions_rejected=0,
        parameters=request.model_dump(mode="json", exclude_none=True),
        skus=skus,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    logger.info("run %d — %d products added, %d rejected", run.request_id, len(skus), len(rejections))

    return GenerationReport(
        **GenerationRunSummary.model_validate(run).model_dump(),
        products_before=before,
        products_after=repository.count_products(db),
        rejected_by_reason=dict(Counter(item.reason for item in rejections)),
    )


def history(db: Session, limit: int = 20) -> list[GenerationRunSummary]:
    """The most recent runs, newest first."""
    runs = (
        db.query(GenerationRun)
        .order_by(GenerationRun.request_id.desc())
        .limit(limit)
        .all()
    )
    return [GenerationRunSummary.model_validate(run) for run in runs]


def remove(db: Session, request_id: int) -> GenerationRemoval | None:
    """Take one run back out of the catalogue.

    Args:
        db: Session on the catalogue the run was loaded into.
        request_id: The run to undo.

    Returns:
        What was removed, or None when no such run was ever recorded. SKUs the run
        produced that are no longer there are reported rather than treated as an error —
        a rebuild between the two calls is the usual reason.
    """
    run = db.get(GenerationRun, request_id)
    if run is None:
        return None

    produced = list(run.skus or [])
    present = {
        sku for (sku,) in db.query(Product.sku).filter(Product.sku.in_(produced)).all()
    }

    specs = _delete_where(db, ProductSpec, ProductSpec.sku, present)
    stock = _delete_where(db, Stock, Stock.sku, present)
    prices = _delete_where(db, Price, Price.sku, present)
    products = _delete_where(db, Product, Product.sku, present)

    db.delete(run)
    db.commit()

    logger.info("run %d withdrawn — %d products removed", request_id, products)

    return GenerationRemoval(
        request_id=request_id,
        products_removed=products,
        specs_removed=specs,
        stock_rows_removed=stock,
        prices_removed=prices,
        already_gone=sorted(set(produced) - present),
        products_after=repository.count_products(db),
    )


def _delete_where(db: Session, model, column, skus: set[str]) -> int:
    if not skus:
        return 0
    return db.query(model).filter(column.in_(skus)).delete(synchronize_session=False)


# ── Drafting ─────────────────────────────────────────────────────────────────


def _draft(
    db: Session, request: GenerationRequest, rng: random.Random
) -> tuple[list[dict], list[Category]]:
    """One draft record per requested product, with a SKU no one else holds."""
    categories = [request.category] if request.category else list(Category)
    brands = request.brands or builder.DEFAULT_BRANDS
    suppliers = [request.supplier_code] if request.supplier_code else _supplier_codes(db)
    band = (
        (request.price_min, request.price_max) if request.price_min is not None else None
    )
    next_number = _next_numbers(db)

    drafts: list[dict] = []
    exhausted: list[Category] = []

    for _ in range(request.count):
        category = rng.choice(categories)
        number = next_number[category]
        if number > builder.SKU_LIMIT:
            exhausted.append(category)
            continue
        next_number[category] = number + 1

        specs = builder.build_specs(category, rng)
        drafts.append(
            {
                "sku": f"{SKU_PREFIXES[category]}-{number}",
                "category": category,
                "brand": rng.choice(brands),
                "description": builder.describe(category, specs, rng),
                "price": builder.price_for(category, rng, band),
                "supplier": rng.choice(suppliers),
                "stock": _stock_for(request, rng),
            }
        )

    return drafts, exhausted


def _stock_for(request: GenerationRequest, rng: random.Random) -> list[tuple[str, int]]:
    """Where the product is held. Pinned to one warehouse, or spread over up to three."""
    if request.warehouse is not None:
        return [(str(request.warehouse), rng.choice(builder.QUANTITIES))]

    places = rng.sample(list(Warehouse), rng.choice([1, 1, 2, 3]))
    return [(str(place), rng.choice(builder.QUANTITIES)) for place in places]


def _next_numbers(db: Session) -> dict[Category, int]:
    """The first free number in each category's SKU range."""
    free = {}
    for category, prefix in SKU_PREFIXES.items():
        highest = (
            db.query(func.max(Product.sku))
            .filter(Product.sku.like(f"{prefix}-____"))
            .scalar()
        )
        free[category] = (
            int(highest.split("-")[1]) + 1 if highest else builder.SKU_START
        )
    return free


def _supplier_codes(db: Session) -> list[str]:
    """The suppliers the catalogue knows. Falls back to the registry on an empty database."""
    codes = [code for (code,) in db.query(Supplier.code).order_by(Supplier.code).all()]
    return codes or [str(code) for code in SupplierCode]


# ── The shapes the source systems use ────────────────────────────────────────


def _raw_rows(drafts: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    today = date.today().isoformat()
    erp, pricing, stock = [], [], []

    for draft in drafts:
        erp.append(
            {
                "item_code": draft["sku"],
                "description": draft["description"],
                "cat": str(draft["category"]),
                "brand": draft["brand"],
                "unit": "ΤΕΜ",
            }
        )
        pricing.append(
            {
                "product_code": draft["sku"],
                "list_price": f"{draft['price']:.2f}",
                "currency": "EUR",
                "updated_at": today,
            }
        )
        for warehouse, quantity in draft["stock"]:
            stock.append(
                {
                    "sku": draft["sku"],
                    "qty_available": str(quantity),
                    "warehouse": warehouse,
                }
            )

    return erp, pricing, stock


def _supplier_entries(drafts: list[dict]) -> list[dict]:
    """The supplier registry as the JSON file writes it: one entry, many SKUs."""
    grouped = defaultdict(list)
    for draft in drafts:
        grouped[str(draft["supplier"])].append(draft["sku"])

    return [{"supplier_code": code, "supplies": skus} for code, skus in grouped.items()]


def _exhausted(categories: list[Category]) -> list[normalizer.Rejection]:
    return [
        normalizer.Rejection("generator", str(category), "no SKU numbers left")
        for category in categories
    ]


# ── Loading ──────────────────────────────────────────────────────────────────


def _persist(
    db: Session,
    products: list[normalizer.CanonicalProduct],
    stock: list[normalizer.CanonicalStock],
) -> tuple[list[str], int, int]:
    """Add what is new. A SKU the catalogue already holds is left alone."""
    known = {sku for (sku,) in db.query(Product.sku).all()}

    added: list[str] = []
    specs_added = 0

    for product in products:
        if product.sku in known:
            continue

        db.add(
            Product(
                sku=product.sku,
                category=product.category,
                brand=product.brand,
                description=product.description,
                unit=product.unit,
                supplier_code=product.supplier_code,
            )
        )
        rows = spec_rows(product)
        db.add_all(rows)
        specs_added += len(rows)

        if product.price is not None:
            db.add(
                Price(
                    sku=product.sku,
                    amount=product.price,
                    currency=product.currency,
                    updated_at=product.price_updated_at,
                )
            )
        added.append(product.sku)

    fresh = set(added)
    stock_added = 0
    for entry in stock:
        if entry.sku not in fresh:
            continue
        db.add(Stock(sku=entry.sku, warehouse=entry.warehouse, quantity=entry.quantity))
        stock_added += 1

    db.commit()
    return added, specs_added, stock_added
