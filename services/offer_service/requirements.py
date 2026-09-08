"""
Customer requirements
=====================
What a salesperson's request comes down to once the specifics are pulled out of it, and
the only shape the retriever and the scenario builder read.
"""

import math
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from services.data_service.categories import (
    ORDERED_LABELS,
    SPEC_TYPES,
    Category,
    is_flag,
    is_numeric,
    label_values,
    specs_for,
)

Operator = Literal["eq", "gte", "lte", "gt", "lt"]

COMPARISONS = ("gte", "lte", "gt", "lt")

# The one thing a request can be ordered on that is not a specification.
PRICE = "price"


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
            if not math.isfinite(self.value):
                raise ValueError(f"{self.key} is never {self.value}, so it filters nothing")
            if self.value <= 0:
                raise ValueError(f"{self.key} is never 0 or less, so {self.value} filters nothing")
        elif is_flag(self.key):
            if not isinstance(self.value, bool):
                raise ValueError(f"{self.key} is on or off, not {self.value!r}")
            if self.op != "eq":
                raise ValueError(f"{self.key} is on or off, so only eq applies")
        else:
            allowed = label_values(self.key)
            if self.value not in allowed:
                raise ValueError(f"{self.value!r} is not one of {allowed}")
            if self.op in COMPARISONS and self.key not in ORDERED_LABELS:
                raise ValueError(f"{self.key} has no order, so only eq applies")
        return self

    def holds(self, held) -> bool:
        """Whether a specification the catalogue reports satisfies this constraint.

        The catalogue stores a flag as the text `true` or `false`, and every string is
        truthy, so a flag is translated before it is compared.
        """
        if self.key in ORDERED_LABELS:
            order = ORDERED_LABELS[self.key]
            if held not in order:
                return False
            return _compare(self.op, order.index(held), order.index(self.value))

        if isinstance(self.value, bool):
            return _flag(held) == self.value

        if isinstance(held, str) or isinstance(self.value, str):
            return held == self.value

        return _compare(self.op, held, self.value)


def _flag(held) -> bool:
    """A flag the way the catalogue stores it, which is the text `true` or `false`."""
    if isinstance(held, bool):
        return held

    return str(held).strip().lower() == "true"


def _compare(op: str, held, wanted) -> bool:
    if op == "eq":
        return held == wanted
    if op == "gte":
        return held >= wanted
    if op == "gt":
        return held > wanted
    if op == "lte":
        return held <= wanted
    return held < wanted


class Ordering(BaseModel):
    """Which end of a range the request is asking for.

    `price` sits here alongside the specifications, and is the one end the index cannot
    find: it is read from the catalogue once the products are in hand.
    """

    key: str = Field(
        ..., description="Something that can be compared, such as `length_m` or `price`"
    )
    end: Literal["max", "min"]

    @field_validator("key")
    @classmethod
    def _comparable(cls, key: str) -> str:
        if key != PRICE and not is_numeric(key) and key not in ORDERED_LABELS:
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
    budget_max: float | None = Field(
        default=None, gt=0, description="A ceiling on the whole order, not on one unit"
    )
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
            if self.order is not None and self.order.key != PRICE:
                named.append(self.order.key)
            stray = [key for key in named if key not in carried]
            if stray:
                raise ValueError(f"{self.category.value} products have no {', '.join(stray)}")
        return self
