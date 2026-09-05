"""
Schemas
=======
What the catalogue service accepts and returns.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from services.data_service.categories import Category, SupplierCode, Warehouse


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


class GenerationRequest(BaseModel):
    """What a generation run is allowed to vary."""

    count: int = Field(10, ge=1, le=100, description="How many products to add")
    seed: int | None = Field(
        None, description="Pass a previous run's seed to reproduce it exactly"
    )
    category: Category | None = Field(
        None, description="Leave empty to spread the products over every category"
    )
    warehouse: Warehouse | None = Field(
        None, description="Pin the new stock to one warehouse instead of spreading it"
    )
    supplier_code: SupplierCode | None = Field(
        None, description="Leave empty to spread the products over the known suppliers"
    )
    brands: list[str] | None = Field(
        None,
        max_length=20,
        description="Defaults to the brands the catalogue already carries",
    )
    price_min: float | None = Field(None, gt=0, description="Overrides the category band")
    price_max: float | None = Field(None, gt=0, description="Overrides the category band")

    @model_validator(mode="after")
    def _check_band(self):
        if self.price_min is not None and self.price_max is not None:
            if self.price_min >= self.price_max:
                raise ValueError("price_min must be below price_max")
        if (self.price_min is None) != (self.price_max is None):
            raise ValueError("give both price_min and price_max, or neither")
        return self


class GenerationRunSummary(BaseModel):
    """A generation run as the database recorded it."""

    request_id: int
    created_at: datetime
    seed: int
    requested: int
    products_added: int
    specs_added: int
    stock_rows_added: int
    rejected: int
    rounds: int
    descriptions_rejected: int
    parameters: dict = Field(default_factory=dict)
    skus: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class GenerationReport(GenerationRunSummary):
    """What one run did to the catalogue, counted before and after."""

    products_before: int
    products_after: int
    rejected_by_reason: dict[str, int] = Field(default_factory=dict)


class GenerationRemoval(BaseModel):
    """What taking a run back out of the catalogue removed."""

    request_id: int
    products_removed: int
    specs_removed: int
    stock_rows_removed: int
    prices_removed: int
    already_gone: list[str] = Field(
        default_factory=list,
        description="SKUs the run produced that the catalogue no longer held",
    )
    products_after: int


class LoadReport(BaseModel):
    """What one pass over the source files put into the catalogue, and what it could not."""

    erp_rows: int
    products_loaded: int
    duplicates: int
    specs_loaded: int
    prices_loaded: int
    stock_rows: int
    stock_loaded: int
    products_without_stock: int
    rejected: int
    rejected_by_reason: dict[str, int] = Field(default_factory=dict)
