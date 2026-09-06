"""
Customer requirements
=====================
What a salesperson's request comes down to once the specifics are pulled out of it, and
the only shape the retriever and the scenario builder read.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from services.data_service.categories import (
    ORDERED_LABELS,
    SPEC_TYPES,
    Category,
    is_flag,
    is_numeric,
    specs_for,
)

Operator = Literal["eq", "gte", "lte", "gt", "lt"]

COMPARISONS = ("gte", "lte", "gt", "lt")


class Constraint(BaseModel):
    """One condition on one specification."""

    key: str = Field(..., description="A specification the catalogue carries, such as `watt`")
    op: Operator = Field(
        default="eq", description="`gt` and `lt` are strict, `gte` and `lte` are not"
    )
    value: bool | float | str

    @field_validator("key")
    @classmethod
    def _in_the_registry(cls, key: str) -> str:
        if key not in SPEC_TYPES:
            raise ValueError(f"{key} is not a specification the catalogue carries")
        return key

    @model_validator(mode="after")
    def _fits_what_it_names(self):
        if is_numeric(self.key):
            if not isinstance(self.value, float | int) or isinstance(self.value, bool):
                raise ValueError(f"{self.key} is a number, not {self.value!r}")
        elif is_flag(self.key):
            if not isinstance(self.value, bool):
                raise ValueError(f"{self.key} is on or off, not {self.value!r}")
            if self.op != "eq":
                raise ValueError(f"{self.key} is on or off, so only eq applies")
        elif self.key in ORDERED_LABELS:
            if self.value not in ORDERED_LABELS[self.key]:
                raise ValueError(f"{self.value!r} is not one of {ORDERED_LABELS[self.key]}")
        elif self.op in COMPARISONS:
            raise ValueError(f"{self.key} has no order, so only eq applies")
        return self


class Ordering(BaseModel):
    """Which end of a specification's range the request is asking for."""

    key: str = Field(..., description="A specification that can be compared, such as `length_m`")
    end: Literal["max", "min"]

    @field_validator("key")
    @classmethod
    def _comparable(cls, key: str) -> str:
        if not is_numeric(key) and key not in ORDERED_LABELS:
            raise ValueError(f"{key} has no order to sit at the end of")
        return key


class CustomerRequirements(BaseModel):
    """A request as the rest of the pipeline gets to see it.

    Everything is optional but the request itself: plenty of real requests name a category
    and nothing else, and one names neither.
    """

    request: str = Field(..., description="What the salesperson wrote, kept as written")
    category: Category | None = None
    quantity: int | None = Field(default=None, gt=0)
    constraints: list[Constraint] = Field(default_factory=list)
    order: Ordering | None = Field(
        default=None, description="Set when the request asks for the end of a range"
    )
    price_min: float | None = Field(default=None, gt=0)
    price_max: float | None = Field(default=None, gt=0)
    immediate: bool = Field(
        default=False, description="Stock has to cover the quantity now, not on reorder"
    )

    @model_validator(mode="after")
    def _holds_together(self):
        if self.price_min is not None and self.price_max is not None:
            if self.price_min >= self.price_max:
                raise ValueError("price_min must be below price_max")

        if self.category is not None:
            carried = specs_for(self.category)
            named = [c.key for c in self.constraints]
            if self.order is not None:
                named.append(self.order.key)
            stray = [key for key in named if key not in carried]
            if stray:
                raise ValueError(f"{self.category.value} products have no {', '.join(stray)}")
        return self
