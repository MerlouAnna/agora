"""
Schemas
=======
What the catalogue service accepts and returns.
"""

from datetime import date

from pydantic import BaseModel, Field


class ProductSummary(BaseModel):
    sku: str
    category: str
    brand: str
    description: str = Field(..., description="The ERP text, specs included")
    unit: str
    supplier_code: str | None = None
    price: float | None = Field(None, description="List price, absent if the source had none")
    currency: str | None = None
    price_updated_at: date | None = None
    specs: dict = Field(default_factory=dict)
    stock_total: int | None = Field(
        None, description="Total across warehouses. Null means no stock record exists."
    )


class StockEntry(BaseModel):
    warehouse: str
    quantity: int


class ProductStock(BaseModel):
    sku: str
    total: int | None = Field(None, description="Null when the warehouse system has no record")
    entries: list[StockEntry] = Field(default_factory=list)


class LookupRequest(BaseModel):
    skus: list[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="One or more SKUs. Pass a single one to read a single product.",
    )

    model_config = {"json_schema_extra": {"example": {"skus": ["PWR-1007", "UPS-1005"]}}}


class CategoryStats(BaseModel):
    category: str
    products: int
    min_price: float | None = None
    max_price: float | None = None
    avg_price: float | None = None


class WarehouseStats(BaseModel):
    warehouse: str
    skus: int
    units: int


class SupplierStats(BaseModel):
    code: str
    name: str
    lead_time_days: int
    reliability_score: float
    products: int


class CatalogueStats(BaseModel):
    products: int
    specs: int
    stock_units: int = Field(..., description="Units held across every warehouse")
    stock_value: float = Field(..., description="Those units at list price, in euro")
    without_stock_record: int = Field(
        ..., description="Products the warehouse system has never heard of"
    )
    without_price: int
    out_of_stock: int = Field(..., description="Products recorded as zero — known, not unknown")
    by_category: list[CategoryStats]
    by_warehouse: list[WarehouseStats]
    by_supplier: list[SupplierStats]
