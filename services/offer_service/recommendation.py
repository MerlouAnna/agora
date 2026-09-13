"""
Offer recommendation
====================
The one offer the salesperson is pointed at, and the sentence that goes with it. The model
reads the offers and picks; it computes nothing, and every code and figure it writes has to
be findable in what it was given, or the answer goes back with the reason attached.

Which sections of the business documents travel with the offers is decided by what the
offers carry, not by what the customer's words happen to resemble.
"""

import json
import logging
import re
import time
from collections.abc import Callable

from pydantic import BaseModel, Field

from services import config, usage
from services.config import settings
from services.offer_service.domain.models import Availability, OfferScenario, Risk
from services.offer_service.prompts.recommendation import SYSTEM
from services.offer_service.rag import policies
from services.offer_service.requirements import CustomerRequirements

logger = logging.getLogger(__name__)

MAX_ROUNDS = 3
TEMPERATURE = 0.0
SERVICE = "offer_service"
PURPOSE = "recommendation"

SKU = re.compile(r"\b[A-Z]{3}-\d{4}\b")
NUMBER = re.compile(r"\d[\d.,]*")
GROUPED = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?")

_client = None

# What an offer has to carry for a section of the documents to be worth putting in front of
# the model. Named by document and heading, never by passage id: an id counts sections from
# the top, so a document re-rendered with one more heading moves every id below it.
GROUNDS = (
    ("politiki-ekptoseon", "Κλιμάκια έκπτωσης όγκου", lambda one: one.discount > 0),
    ("politiki-ekptoseon", "Έγκριση πάνω από το όριο", lambda one: one.needs_approval),
    (
        "oroi-paradosis",
        "Άμεση παράδοση",
        lambda one: one.availability == Availability.SAME_DAY,
    ),
    (
        "oroi-paradosis",
        "Μεταφορά μεταξύ αποθηκών",
        lambda one: one.availability == Availability.TRANSFER,
    ),
    (
        "oroi-paradosis",
        "Παραγγελία εκτός αποθέματος",
        lambda one: one.availability == Availability.ORDERED,
    ),
    ("oroi-paradosis", "Κόστος μεταφορικών", lambda one: one.shipping > 0),
    (
        "oroi-paradosis",
        "Πότε ένας προμηθευτής δεν δεσμεύεται για επείγουσα παραγγελία",
        lambda one: one.risk == Risk.HIGH,
    ),
)


class NoOffers(ValueError):
    """There is nothing to recommend, which is the graph's business and not this node's."""


class RecommendationFailed(RuntimeError):
    """The model could not answer within the data it was given."""


class ModelUnavailable(RuntimeError):
    """The recommendation model could not be reached."""


class Written(BaseModel):
    """The model's answer, before it has been held against the offers."""

    sku: str = Field(..., description="The SKU of the offer being recommended, exactly as given")
    because: str = Field(
        ...,
        description="For the salesperson: what decided it, and the offer you did not pick",
    )
    watch_out: list[str] = Field(
        ..., description="Every condition the customer would otherwise discover later"
    )
    text: str = Field(
        ..., description="What the salesperson sends, in Greek, two to four sentences"
    )


class Recommendation(BaseModel):
    """The answer, with the sections it was written against."""

    sku: str
    because: str
    watch_out: list[str]
    text: str
    rounds_used: int
    sections: list[str]


def recommend(
    offers: list[OfferScenario],
    requirements: CustomerRequirements,
    ask: Callable[[dict, str | None], Written] | None = None,
    rounds: int = MAX_ROUNDS,
) -> Recommendation:
    """Point the salesperson at one offer, in words that stay inside the data.

    Args:
        offers: What the validator let through, in the order they were built.
        requirements: What was asked for, whose own numbers the answer may also use.
        ask: What actually talks to the model. Replaced in tests.
        rounds: How many times an answer may be sent back before it is given up on.

    Returns:
        The offer chosen, why, what to watch out for, and the text to send.

    Raises:
        NoOffers: There is nothing to recommend.
        RecommendationFailed: Every round invented something.
    """
    if not offers:
        raise NoOffers("nothing survived the check, so there is nothing to recommend")

    ask = ask or _ask_model
    sections = grounds(offers)
    context = _context(offers, requirements, sections)
    allowed = _allowed(offers, requirements)

    problem = None
    for attempt in range(1, rounds + 1):
        written = ask(context, problem)
        problem = _invented(written, offers, allowed)
        if problem is None:
            return Recommendation(
                sku=written.sku,
                because=written.because.strip(),
                watch_out=[one.strip() for one in written.watch_out if one.strip()],
                text=written.text.strip(),
                rounds_used=attempt,
                sections=[passage.id for passage in sections],
            )

        logger.info("round %d sent back — %s", attempt, problem)

    raise RecommendationFailed(problem or "the answer never stayed inside the offers")


def grounds(offers: list[OfferScenario]) -> list:
    """The sections of the documents these particular offers put in play."""
    wanted = {
        (document, heading)
        for document, heading, holds in GROUNDS
        if any(holds(one) for one in offers)
    }
    if not wanted:
        return []

    return [
        passage
        for passage in policies.read_all()
        if (passage.metadata["document"], passage.metadata["section"]) in wanted
    ]


def _context(
    offers: list[OfferScenario], requirements: CustomerRequirements, sections: list
) -> dict:
    return {
        "request": requirements.request,
        "offers": [_offer(one) for one in offers],
        "policy": [
            {
                "document": passage.metadata["document"],
                "section": passage.metadata["section"],
                "text": passage.text,
            }
            for passage in sections
        ],
    }


def _offer(one: OfferScenario) -> dict:
    line = one.lines[0]
    return {
        "strategies": [strategy.value for strategy in one.strategies],
        "sku": line.sku,
        "description": line.description,
        "quantity": line.quantity,
        "unit_price": line.unit_price,
        "net": one.net,
        "discount": one.discount,
        "discount_rate": one.discount_rate,
        "shipping": one.shipping,
        "total": one.total,
        "availability": one.availability.value,
        "days": one.days,
        "risk": one.risk.value,
        "needs_approval": one.needs_approval,
        "notes": one.notes,
    }


def _allowed(offers: list[OfferScenario], requirements: CustomerRequirements) -> set[str]:
    """Every number the answer is allowed to contain, as the text would write it."""
    figures: list[float | int | None] = [
        requirements.quantity,
        requirements.price_min,
        requirements.price_max,
        requirements.budget_max,
    ]
    for constraint in requirements.constraints:
        if isinstance(constraint.value, (int, float)) and not isinstance(constraint.value, bool):
            figures.append(constraint.value)

    for one in offers:
        figures += [one.net, one.discount, one.shipping, one.total, one.days]
        figures += [one.discount_rate, round(one.discount_rate * 100)]
        for line in one.lines:
            figures += [line.quantity, line.unit_price, line.line_total]
            for source in line.sources:
                figures.append(source.quantity)
        for spec in _numbers(" ".join([line.description for line in one.lines] + one.notes)):
            figures.append(spec)

    return {_plain(figure) for figure in figures if figure is not None}


def _invented(written: Written, offers: list[OfferScenario], allowed: set[str]) -> str | None:
    """What in the answer cannot be found in what the model was given."""
    codes = {line.sku for one in offers for line in one.lines}
    if written.sku not in codes:
        return f"{written.sku} is not one of the offers — pick from {', '.join(sorted(codes))}"

    said = " ".join([written.because, written.text, *written.watch_out])
    strange = sorted(set(SKU.findall(said)) - codes)
    if strange:
        return f"{', '.join(strange)} is not in the offers, and no other product may be named"

    clean = SKU.sub("", said)
    figures = sorted({found for found in _numbers(clean) if _plain(found) not in allowed})
    if figures:
        return (
            f"{', '.join(_plain(figure) for figure in figures)} appears nowhere in the offers "
            f"or the request — «{_where(clean, figures[0])}». Write only figures that are there"
        )

    return None


def _where(said: str, figure: float) -> str:
    """The phrase a stray figure sits in, quoted back so it is clear which one is meant."""
    for match in NUMBER.finditer(said):
        if _read(match.group().strip(".,")) == figure:
            return said[max(0, match.start() - 30) : match.end() + 30].strip()

    return ""


def _numbers(said: str) -> list[float]:
    """Every figure in a piece of Greek text, read the way Greek writes them.

    3.656,44 is one number and not two: the dot groups thousands and the comma is the
    decimal. A token that cannot be read at all is passed over rather than reported, since
    a guard that fires on what it cannot parse is worse than one that stays quiet.
    """
    found = []
    for raw in NUMBER.findall(said):
        figure = _read(raw.strip(".,"))
        if figure is not None:
            found.append(figure)

    return found


def _read(raw: str) -> float | None:
    if GROUPED.fullmatch(raw):
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(",") == 1 and "." not in raw:
        raw = raw.replace(",", ".")
    elif "," in raw or raw.count(".") > 1:
        return None

    try:
        return float(raw)
    except ValueError:
        return None


def _plain(figure: float | int) -> str:
    number = float(figure)
    return str(int(number)) if number.is_integer() else f"{number:.2f}"


def client():
    """The OpenAI client, built once. The import is what costs, so it happens behind a log line."""
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


def _ask_model(context: dict, problem: str | None) -> Written:
    """One call, with the refusal from the round before carried into the request."""
    talk = client()
    asked = context if problem is None else context | {"fix": problem}

    started = time.monotonic()
    try:
        completion = talk.chat.completions.parse(
            model=settings.llm_model,
            temperature=TEMPERATURE,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(asked, ensure_ascii=False)},
            ],
            response_format=Written,
        )
    except Exception as exc:
        usage.record(
            SERVICE,
            PURPOSE,
            settings.llm_model,
            duration_ms=int((time.monotonic() - started) * 1000),
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
        duration_ms=int((time.monotonic() - started) * 1000),
    )

    written = completion.choices[0].message.parsed
    if written is None:
        raise ModelUnavailable("the model answered with nothing to parse")

    return written
