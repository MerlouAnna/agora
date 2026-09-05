"""
Repository
==========
Every query the catalogue answers. Specs live one row per spec, so a search with two
numeric conditions needs two joins onto the same table — that assembly happens here and
nowhere else.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from services.data_service.models import Price, Product, ProductSpec, Stock, Supplier

DEFAULT_LIMIT = 20


def search_products(
    db: Session,
    category: str | None = None,
    min_watt: float | None = None,
    min_length_m: float | None = None,
    max_price: float | None = None,
    min_stock: int | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[Product]:
    """Products matching every condition given. Conditions left out are not applied.

    Args:
        db: Open session.
        category: Exact category code.
        min_watt: Lowest acceptable wattage.
        min_length_m: Lowest acceptable length in metres.
        max_price: Highest acceptable list price.
        min_stock: Lowest acceptable total across warehouses. Products with no stock
            record at all are left out when this is set, since their stock is unknown
            rather than sufficient.
        limit: How many rows at most.

    Returns:
        The matching products, ordered by SKU.
    """
    query = db.query(Product)

    if category is not None:
        query = query.filter(Product.category == category)

    query = _with_spec_minimum(query, "watt", min_watt)
    query = _with_spec_minimum(query, "length_m", min_length_m)

    if max_price is not None:
        query = query.join(Price, Price.sku == Product.sku).filter(Price.amount <= max_price)

    if min_stock is not None:
        totals = _stock_totals_subquery(db)
        query = query.join(totals, totals.c.sku == Product.sku).filter(
            totals.c.total >= min_stock
        )

    return query.order_by(Product.sku).limit(limit).all()


def get_product(db: Session, sku: str) -> Product | None:
    return db.query(Product).filter(Product.sku == sku).first()


def get_products(db: Session, skus: list[str]) -> list[Product]:
    return db.query(Product).filter(Product.sku.in_(skus)).order_by(Product.sku).all()


def get_stock(db: Session, sku: str) -> list[Stock]:
    return db.query(Stock).filter(Stock.sku == sku).order_by(Stock.warehouse).all()


def get_specs(db: Session, skus: list[str]) -> dict[str, dict]:
    """The specs of several products at once, keyed by SKU."""
    rows = db.query(ProductSpec).filter(ProductSpec.sku.in_(skus)).all()

    specs: dict[str, dict] = {sku: {} for sku in skus}
    for row in rows:
        if row.value_num is None:
            specs[row.sku][row.key] = row.value_text
        elif row.value_num.is_integer():
            specs[row.sku][row.key] = int(row.value_num)
        else:
            specs[row.sku][row.key] = row.value_num

    return specs


def get_stock_totals(db: Session, skus: list[str]) -> dict[str, int]:
    """Total quantity per SKU. A SKU with no stock record is absent from the result."""
    rows = (
        db.query(Stock.sku, func.sum(Stock.quantity))
        .filter(Stock.sku.in_(skus))
        .group_by(Stock.sku)
        .all()
    )
    return {sku: int(total) for sku, total in rows}


def get_prices(db: Session, skus: list[str]) -> dict[str, Price]:
    rows = db.query(Price).filter(Price.sku.in_(skus)).all()
    return {row.sku: row for row in rows}


# ── Overview ──────────────────────────────────────────────────────────────────


def count_products(db: Session) -> int:
    return db.query(func.count(Product.sku)).scalar()


def count_specs(db: Session) -> int:
    return db.query(func.count(ProductSpec.id)).scalar()


def stock_totals(db: Session) -> tuple[int, float]:
    """Units held across every warehouse, and what they are worth at list price."""
    units = db.query(func.sum(Stock.quantity)).scalar() or 0
    value = (
        db.query(func.sum(Price.amount * Stock.quantity))
        .join(Stock, Stock.sku == Price.sku)
        .scalar()
        or 0.0
    )
    return int(units), round(value, 2)


def by_category(db: Session) -> list:
    return (
        db.query(
            Product.category,
            func.count(Product.sku.distinct()),
            func.min(Price.amount),
            func.max(Price.amount),
            func.avg(Price.amount),
        )
        .outerjoin(Price, Price.sku == Product.sku)
        .group_by(Product.category)
        .order_by(Product.category)
        .all()
    )


def by_warehouse(db: Session) -> list:
    return (
        db.query(Stock.warehouse, func.count(Stock.sku), func.sum(Stock.quantity))
        .group_by(Stock.warehouse)
        .order_by(Stock.warehouse)
        .all()
    )


def by_supplier(db: Session) -> list:
    return (
        db.query(
            Supplier.code,
            Supplier.name,
            Supplier.lead_time_days,
            Supplier.reliability_score,
            func.count(Product.sku),
        )
        .outerjoin(Product, Product.supplier_code == Supplier.code)
        .group_by(Supplier.code)
        .order_by(Supplier.code)
        .all()
    )


def gaps(db: Session) -> tuple[int, int, int]:
    """Products the catalogue cannot fully answer for: no stock record, no price, none left."""
    without_stock = (
        db.query(func.count(Product.sku))
        .outerjoin(Stock, Stock.sku == Product.sku)
        .filter(Stock.sku.is_(None))
        .scalar()
    )
    without_price = (
        db.query(func.count(Product.sku))
        .outerjoin(Price, Price.sku == Product.sku)
        .filter(Price.sku.is_(None))
        .scalar()
    )
    totals = _stock_totals_subquery(db)
    out_of_stock = (
        db.query(func.count())
        .select_from(totals)
        .filter(totals.c.total == 0)
        .scalar()
    )
    return without_stock, without_price, out_of_stock


def _with_spec_minimum(query, key: str, minimum: float | None):
    if minimum is None:
        return query

    spec = aliased(ProductSpec)
    return query.join(spec, spec.sku == Product.sku).filter(
        spec.key == key, spec.value_num >= minimum
    )


def _stock_totals_subquery(db: Session):
    return (
        db.query(Stock.sku.label("sku"), func.sum(Stock.quantity).label("total"))
        .group_by(Stock.sku)
        .subquery()
    )
