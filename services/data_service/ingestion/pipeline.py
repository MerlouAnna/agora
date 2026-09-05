"""
Ingestion pipeline
==================
Loads the raw exports, normalizes them and rebuilds the catalogue tables, then reports
what went in and what did not.

Run from the repository root:  python -m services.data_service.ingestion.pipeline
"""

import logging
from collections import Counter

from pydantic import BaseModel
from sqlalchemy.orm import Session

from services.data_service.categories import is_numeric
from services.data_service.database import SessionLocal, TableBase, engine
from services.data_service.ingestion import loader, normalizer
from services.data_service.models import Price, Product, ProductSpec, Stock, Supplier

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


class LoadReport(BaseModel):
    erp_rows: int
    products_loaded: int
    duplicates: int
    specs_loaded: int
    prices_loaded: int
    stock_rows: int
    stock_loaded: int
    products_without_stock: int
    rejected: int
    rejected_by_reason: dict[str, int]


def run() -> LoadReport:
    erp_rows = loader.load_erp()
    stock_rows = loader.load_stock()
    pricing_rows = loader.load_pricing()
    suppliers = loader.load_suppliers()

    products, product_rejections, duplicates = normalizer.normalize_products(
        erp_rows, pricing_rows, suppliers
    )
    stock, stock_rejections = normalizer.normalize_stock(
        stock_rows, {p.sku for p in products}
    )

    rejections = product_rejections + stock_rejections
    with SessionLocal() as db:
        _rebuild(db, products, stock, suppliers)

    report = LoadReport(
        erp_rows=len(erp_rows),
        products_loaded=len(products),
        duplicates=duplicates,
        specs_loaded=sum(len(p.specs) for p in products),
        prices_loaded=sum(1 for p in products if p.price is not None),
        stock_rows=len(stock_rows),
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
    """Replace the catalogue with what the raw files currently say."""
    TableBase.metadata.create_all(bind=engine)

    for model in (ProductSpec, Stock, Price, Product, Supplier):
        db.query(model).delete()

    db.add_all(
        Supplier(
            code=entry["supplier_code"],
            name=entry["name"],
            lead_time_days=entry["lead_time_days"],
            reliability_score=entry["reliability_score"],
        )
        for entry in suppliers
    )

    for product in products:
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
        db.add_all(_spec_rows(product))

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


def _spec_rows(product: normalizer.CanonicalProduct) -> list[ProductSpec]:
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
    logger.info("ERP rows read        %d", report.erp_rows)
    logger.info("products loaded      %d", report.products_loaded)
    logger.info("duplicate SKUs       %d", report.duplicates)
    logger.info("specs loaded         %d", report.specs_loaded)
    logger.info("prices loaded        %d", report.prices_loaded)
    logger.info("stock rows read      %d", report.stock_rows)
    logger.info("stock rows loaded    %d", report.stock_loaded)
    logger.info("products with no stock record %d", report.products_without_stock)
    logger.info("rejected             %d", report.rejected)

    for reason, count in report.rejected_by_reason.items():
        logger.info("   %-24s %d", reason, count)
    for rejection in rejections:
        logger.info("   %s %s — %s", rejection.source, rejection.identifier, rejection.reason)


if __name__ == "__main__":
    run()
