"""
Requirement extraction
======================
A salesperson's request read into the shape the retriever takes. The model proposes and
the `CustomerRequirements` validators decide; whatever they refuse goes back to the model
with their own sentence attached — three rounds, after which the request is handed back
unanswered rather than searched on a guess.

Nothing here touches the catalogue, and the call to the model is a parameter, so the
repair loop can be exercised without one.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from services import config, usage
from services.config import settings
from services.data_service.categories import (
    ORDERED_LABELS,
    SPEC_TYPES,
    Category,
    is_flag,
    is_numeric,
)
from services.offer_service.prompts import extraction as prompt
from services.offer_service.requirements import (
    PRICE,
    Constraint,
    CustomerRequirements,
    Operator,
)

logger = logging.getLogger(__name__)

MAX_ROUNDS = 3
SERVICE = "offer_service"
PURPOSE = "requirement-extraction"

TEMPERATURE = 0.0

# The specifications the model is allowed to name, straight from the registry.
SpecKey = StrEnum("SpecKey", {key.upper(): key for key in SPEC_TYPES})

# And the ones it can order on: whatever compares, plus the price.
OrderKey = StrEnum(
    "OrderKey",
    {key.upper(): key for key in SPEC_TYPES if is_numeric(key) or key in ORDERED_LABELS}
    | {"PRICE": PRICE},
)

# What the model is asked to call each end of a range.
ENDS = {"highest": "max", "lowest": "min"}

TRUE = ("true", "yes", "ναι", "1")
FALSE = ("false", "no", "όχι", "0")

_client = None


class ModelUnavailable(RuntimeError):
    """The extraction model could not be reached."""


class ExtractionFailed(RuntimeError):
    """Three rounds, and the request never came back in a shape the catalogue accepts."""


class ExtractedConstraint(BaseModel):
    key: SpecKey = Field(..., description="A specification the named category carries")
    op: Operator = Field(..., description="`eq` unless the request names a floor or a ceiling")
    value: str = Field(
        ..., description="Written as text. A number carries no unit, and is never money"
    )


class ExtractedOrdering(BaseModel):
    """Only for a request built on a superlative: «το πιο μακρύ», «the cheapest»."""

    key: OrderKey = Field(..., description="What the range is measured on")
    end: Literal["highest", "lowest"]


class Extracted(BaseModel):
    """What the model is asked for. The validators in `requirements` are what judge it."""

    category: Category | None = Field(
        ..., description="Null unless the request makes one category plain"
    )
    quantity: int | None = Field(
        ..., description="How many units. Null when the request does not say, and never 0"
    )
    constraints: list[ExtractedConstraint] = Field(
        ..., description="One per specification the request names, and empty when it names none"
    )
    order: ExtractedOrdering | None = Field(
        ..., description="Null unless the request is built on a superlative"
    )
    price_min: float | None = Field(
        ...,
        description=(
            "The least the customer will pay per unit, in euro — «από 200 ευρώ και πάνω». "
            "Null when the request names no floor, and never 0"
        ),
    )
    price_max: float | None = Field(
        ...,
        description=(
            "The most the customer will pay per unit, in euro — this is where «μέχρι 900 "
            "ευρώ» goes. Null when the request names no ceiling, and never 0"
        ),
    )
    budget_max: float | None = Field(
        ...,
        description=(
            "The most the customer will pay for the order as a whole, in euro, and only "
            "when the request says the figure covers all of it. Null otherwise, never 0"
        ),
    )
    immediate: bool = Field(
        ..., description="True only when the request says the stock has to be there now"
    )


@dataclass(frozen=True)
class Extraction:
    """What the request came down to, and what it took to get there."""

    requirements: CustomerRequirements
    trace: dict


def extract(
    request: str,
    ask: Callable[[str, str | None], Extracted] | None = None,
    rounds: int = MAX_ROUNDS,
) -> Extraction:
    """Read one request into the requirements the retriever searches on.

    Args:
        request: What the salesperson wrote, in Greek or English.
        ask: What actually talks to the model. Replaced in tests.
        rounds: How many times a refused answer may be sent back.

    Returns:
        The requirements, and a trace of what was refused on the way.

    Raises:
        ExtractionFailed: Every round was refused.
        ModelUnavailable: The model could not be reached.
    """
    ask = ask or _ask_model

    refused: list[str] = []
    for used in range(1, rounds + 1):
        answer = ask(request, refused[-1] if refused else None)
        try:
            requirements = _requirements(request, answer)
        except ValueError as exc:
            refused.append(_readable(exc))
            logger.info("round %d — the extraction was sent back: %s", used, refused[-1])
            continue

        trace: dict = {"rounds": used}
        if refused:
            trace |= {"refused": refused}
        return Extraction(requirements, trace)

    raise ExtractionFailed(refused[-1] if refused else "no round was allowed to run")


def _requirements(request: str, answer: Extracted) -> CustomerRequirements:
    """The model's answer as the pipeline's own type, or the refusal that says why not."""
    return CustomerRequirements(
        request=request,
        category=answer.category,
        quantity=answer.quantity,
        constraints=[_constraint(written) for written in answer.constraints],
        order=_ordering(answer.order),
        price_min=answer.price_min,
        price_max=answer.price_max,
        budget_max=answer.budget_max,
        immediate=answer.immediate,
    )


def _ordering(written: ExtractedOrdering | None) -> dict | None:
    return None if written is None else {"key": written.key.value, "end": ENDS[written.end]}


def _constraint(written: ExtractedConstraint) -> Constraint:
    key = written.key.value

    return Constraint(key=key, op=written.op, value=_typed(key, written.value))


def _typed(key: str, value: str):
    """The value as the specification holds it. Everything arrives as text."""
    if is_numeric(key):
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"{key} is a number, and {value!r} is not one") from None

    if is_flag(key):
        if value.strip().casefold() in TRUE:
            return True
        if value.strip().casefold() in FALSE:
            return False
        raise ValueError(f"{key} is on or off, not {value!r}")

    return value.strip()


def _readable(exc: Exception) -> str:
    """The refusal as one sentence the model can act on, without pydantic's furniture."""
    if not isinstance(exc, ValidationError):
        return str(exc)

    return "; ".join(_sentence(error) for error in exc.errors())


def _sentence(error: dict) -> str:
    where = ".".join(str(part) for part in error["loc"])
    said = error["msg"].removeprefix("Value error, ")

    return f"{where}: {said}" if where else said


def client():
    """The OpenAI client, built once per process."""
    global _client

    if _client is None:
        if not settings.openai_api_key:
            raise ModelUnavailable("no OPENAI_API_KEY in the environment")

        logger.info(
            "loading the OpenAI client — key %s, read from %s",
            config.key_fingerprint(),
            config.key_source(),
        )
        from openai import OpenAI

        _client = OpenAI(api_key=settings.openai_api_key)
        logger.info("client ready, talking to %s", settings.llm_model)

    return _client


def _ask_model(request: str, problem: str | None) -> Extracted:
    """One call, with the refusal from the previous round when there was one."""
    talk = client()
    asked = {"request": request}
    if problem is not None:
        asked["fix"] = problem

    started = time.monotonic()
    try:
        completion = talk.chat.completions.parse(
            model=settings.llm_model,
            temperature=TEMPERATURE,
            messages=[
                {"role": "system", "content": prompt.system()},
                {"role": "user", "content": json.dumps(asked, ensure_ascii=False)},
            ],
            response_format=Extracted,
        )
    except Exception as exc:
        usage.record(
            SERVICE,
            PURPOSE,
            settings.llm_model,
            duration_ms=_elapsed(started),
            ok=False,
            detail=str(exc)[:300],
        )
        raise ModelUnavailable(f"{settings.llm_model} did not answer: {exc}") from exc

    spent = completion.usage
    usage.record(
        SERVICE,
        PURPOSE,
        completion.model,
        prompt_tokens=spent.prompt_tokens if spent else 0,
        completion_tokens=spent.completion_tokens if spent else 0,
        duration_ms=_elapsed(started),
    )

    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ModelUnavailable(f"{settings.llm_model} answered with nothing to read")

    return parsed


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
