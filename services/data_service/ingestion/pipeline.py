"""
Ingestion pipeline
==================
Loads the catalogue file, normalizes it and rebuilds the tables, then reports what went in
and what did not.

Run from the repository root:  python -m services.data_service.ingestion.pipeline
"""

import logging
from collections import Counter

from sqlalchemy.orm import Session

from services.data_service.categories import is_numeric
from services.data_service.database import SessionLocal, TableBase
from services.data_service.ingestion import loader, normalizer
from services.data_service.models import (
    GenerationRun,
    Price,
    Product,
    ProductSpec,
    Stock,
    Supplier,
)
from services.data_service.schemas import LoadReport

logger = logging.getLogger(__name__)


def run(db: Session | None = None) -> LoadReport:
    """Read the four source files and rebuild the catalogue from them.

    Args:
        db: Session to rebuild through. A session of its own is opened when none is given,
            which is how the module runs from the command line.

    Returns:
        What went in, and what was left out and why.
    """
    catalog = loader.load_catalog()
    records, suppliers = catalog["products"], catalog["suppliers"]

    products, stock, rejections = normalizer.normalize_catalog(records)
    duplicates = sum(1 for r in rejections if r.reason == "duplicate SKU")

    if db is not None:
        _rebuild(db, products, stock, suppliers)
    else:
        with SessionLocal() as session:
            _rebuild(session, products, stock, suppliers)

    report = LoadReport(
        source="catalog.json",
        records_read=len(records),
        products_loaded=len(products),
        duplicates=duplicates,
        specs_loaded=sum(len(p.specs) for p in products),
        prices_loaded=sum(1 for p in products if p.price is not None),
        stock_entries_read=sum(len(r.get("stock", [])) for r in records),
        stock_loaded=len(stock),
        products_without_stock=len(products) - len({e.sku for e in stock}),
        rejected=len(rejections),
        rejected_by_reason=dict(Counter(r.reason for r in rejections)),
    )

    _log(report, rejections)
    return report


def _rebuild(
    db: Session,
    products: list[normalizer.CanonicalProduct],
    stock: list[normalizer.CanonicalStock],
    suppliers: list[dict],
) -> None:
    """Replace the catalogue with what the raw files currently say.

    Everything the generation endpoint added goes with it, history included — a rebuild
    is a return to the four source files, and a run log pointing at SKUs that no longer
    exist would be worse than no log at all.
    """
    TableBase.metadata.create_all(bind=db.get_bind())

    for model in (ProductSpec, Stock, Price, Product, Supplier, GenerationRun):
        db.query(model).delete()

    db.add_all(Supplier(**entry) for entry in suppliers)

    for product in products:
        db.add(
            Product(
                sku=product.sku,
                category=product.category,
                brand=product.brand,
                description=product.description,
                web_description=product.web_description,
                unit=product.unit,
                supplier_code=product.supplier_code,
            )
        )
        db.add_all(spec_rows(product))

        if product.price is not None:
            db.add(
                Price(
                    sku=product.sku,
                    amount=product.price,
                    currency=product.currency,
                    updated_at=product.price_updated_at,
                )
            )

    db.add_all(
        Stock(sku=entry.sku, warehouse=entry.warehouse, quantity=entry.quantity)
        for entry in stock
    )

    db.commit()


def spec_rows(product: normalizer.CanonicalProduct) -> list[ProductSpec]:
    rows = []

    for key, value in product.specs.items():
        if is_numeric(key):
            rows.append(ProductSpec(sku=product.sku, key=key, value_num=float(value)))
        else:
            # Labels keep the casing the source used, so IP67 stays IP67. Only the
            # true/false ones are forced down, since Python capitalises them.
            text = str(value).lower() if isinstance(value, bool) else str(value)
            rows.append(ProductSpec(sku=product.sku, key=key, value_text=text))

    return rows


def _log(report: LoadReport, rejections: list[normalizer.Rejection]) -> None:
    logger.info("read from            %s", report.source)
    logger.info("records read         %d", report.records_read)
    logger.info("products loaded      %d", report.products_loaded)
    logger.info("duplicate SKUs       %d", report.duplicates)
    logger.info("specs loaded         %d", report.specs_loaded)
    logger.info("prices loaded        %d", report.prices_loaded)
    logger.info("stock entries read   %d", report.stock_entries_read)
    logger.info("stock rows loaded    %d", report.stock_loaded)
    logger.info("products with no stock record %d", report.products_without_stock)
    logger.info("rejected             %d", report.rejected)

    for reason, count in report.rejected_by_reason.items():
        logger.info("   %-24s %d", reason, count)
    for rejection in rejections:
        logger.info("   %s %s — %s", rejection.source, rejection.identifier, rejection.reason)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run()
