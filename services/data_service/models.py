"""
Catalogue models
================
The tables the catalogue service owns: products and their specs, stock per warehouse,
prices, and the suppliers behind them.
"""

from sqlalchemy import (
    Column,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from services.data_service.database import TableBase


class Product(TableBase):
    """One row per SKU. The description is the ERP's own text, kept as it arrived."""

    __tablename__ = "products"

    sku = Column(String, primary_key=True, index=True)
    category = Column(String, index=True)
    brand = Column(String)
    description = Column(String)
    unit = Column(String, default="ΤΕΜ")
    supplier_code = Column(String, ForeignKey("suppliers.code"), index=True)


class ProductSpec(TableBase):
    """One row per specification. Numbers go in value_num, labels in value_text."""

    __tablename__ = "product_specs"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String, ForeignKey("products.sku"), index=True)
    key = Column(String, index=True)
    value_num = Column(Float, nullable=True)
    value_text = Column(String, nullable=True)

    __table_args__ = (UniqueConstraint("sku", "key"),)


class Stock(TableBase):
    """Quantity per warehouse. A SKU with no row here has unknown stock, not zero."""

    __tablename__ = "stock"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String, ForeignKey("products.sku"), index=True)
    warehouse = Column(String, index=True)
    quantity = Column(Integer)

    __table_args__ = (UniqueConstraint("sku", "warehouse"),)


class Price(TableBase):
    """The current list price, one row per SKU."""

    __tablename__ = "prices"

    sku = Column(String, ForeignKey("products.sku"), primary_key=True)
    amount = Column(Float)
    currency = Column(String, default="EUR")
    updated_at = Column(Date)


class Supplier(TableBase):
    """Suppliers, with the lead time and reliability score procurement keeps for each.Anything below 0.80 is not offered for an urgent order."""

    __tablename__ = "suppliers"

    code = Column(String, primary_key=True, index=True)
    name = Column(String)
    lead_time_days = Column(Integer)
    reliability_score = Column(Float)
