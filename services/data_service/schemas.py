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
    description: str = Field(..., description="The ERP line, terse, specs included")
    web_description: str | None = Field(
        default=None, description="What the shop shows a customer. This is the text worth embedding."
    )
    unit: str
    supplier_code: str | None = None
    price: float | None = Field(default=None, description="List price, absent if the source had none")
    currency: str | None = None
    price_updated_at: date | None = None
    specs: dict = Field(default_factory=dict)
    stock_total: int | None = Field(
        default=None, description="Total across warehouses. Null means no stock record exists."
    )


class StockEntry(BaseModel):
    warehouse: str
    quantity: int


class ProductStock(BaseModel):
    sku: str
    total: int | None = Field(default=None, description="Null when the warehouse system has no record")
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

    count: int = Field(default=10, ge=1, le=100, description="How many products to add")
    seed: int | None = Field(
        default=None, description="Pass a previous run's seed to reproduce it exactly"
    )
    category: Category | None = Field(
        default=None, description="Leave empty to spread the products over every category"
    )
    warehouse: Warehouse | None = Field(
        default=None, description="Pin the new stock to one warehouse instead of spreading it"
    )
    supplier_code: SupplierCode | None = Field(
        default=None, description="Leave empty to spread the products over the known suppliers"
    )
    brands: list[str] | None = Field(
        default=None,
        max_length=20,
        description="Defaults to the brands the catalogue already carries",
    )
    price_min: float | None = Field(default=None, gt=0, description="Overrides the category band")
    price_max: float | None = Field(default=None, gt=0, description="Overrides the category band")
    noise: bool = Field(
        default=True,
        description="Write the rows the way the source systems write them, mistakes included",
    )

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
    products: list[ProductSummary] = Field(
        default_factory=list,
        description="Every product the run added, as the catalogue now holds it",
    )


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
    """What one load put into the catalogue, and what it could not."""

    source: str = Field(..., description="Where the records came from")
    request_id: int | None = Field(
        default=None, description="Set for an import, so it can be taken back out again"
    )
    records_read: int
    products_loaded: int
    duplicates: int
    specs_loaded: int
    prices_loaded: int
    stock_entries_read: int
    stock_loaded: int
    products_without_stock: int
    rejected: int
    rejected_by_reason: dict[str, int] = Field(default_factory=dict)
    products: list[ProductSummary] = Field(
        default_factory=list,
        description="What was added. Left out by a full rebuild, which adds everything",
    )


class UsageLine(BaseModel):
    """One way of slicing the model spend."""

    label: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float


class UsageReport(BaseModel):
    """Everything the project has spent on models, and what asked for it."""

    calls: int
    failed: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float = Field(
        ..., description="At list prices recorded in services/usage.py — an estimate, not a bill"
    )
    first_call: datetime | None = None
    last_call: datetime | None = None
    by_model: list[UsageLine] = Field(default_factory=list)
    by_purpose: list[UsageLine] = Field(default_factory=list)
    by_day: list[UsageLine] = Field(default_factory=list)


class SchemaColumn(BaseModel):
    name: str
    type: str
    nullable: bool
    primary_key: bool


class SchemaTable(BaseModel):
    name: str
    rows: int
    columns: list[SchemaColumn]
    references: dict[str, str] = Field(
        default_factory=dict, description="Column to the table.column it points at"
    )


class CatalogueSchema(BaseModel):
    """What there is to query, and a few queries to start from."""

    tables: list[SchemaTable]
    examples: list[str]


class QueryRequest(BaseModel):
    sql: str = Field(..., min_length=1, description="One SELECT statement")
    limit: int = Field(default=100, ge=1, le=500, description="How many rows to read back")

    model_config = {
        "json_schema_extra": {
            "example": {
                "sql": "select category, count(*) as products from products group by category",
                "limit": 100,
            }
        }
    }


class QueryResult(BaseModel):
    columns: list[str]
    rows: list[list] = Field(default_factory=list)
    row_count: int
    truncated: bool = Field(..., description="There were more rows than the limit asked for")
    elapsed_ms: int
