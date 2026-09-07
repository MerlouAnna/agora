"""
Retrieval measurement
=====================
Runs the requests in tests/data/retrieval_eval.json twice: once on the ranking alone, to
say what each half of the search is worth, and once with the request's constraints as
well, which is what the system actually does.

The expected answers were computed with SQL against the catalogue, not chosen by eye, so
the number this prints is a fact about the retriever and not about anyone's judgement.

Run from the repository root:  python -m tools.measure_retrieval
"""

import json
import logging
import sys
from pathlib import Path

from services.data_service import repository
from services.data_service.database import SessionLocal
from services.data_service.models import Price, Product, Stock
from services.offer_service.rag import embeddings, lexical, retriever
from services.offer_service.rag.documents import build_cards
from services.offer_service.requirements import PRICE, CustomerRequirements

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EVAL_FILE = Path(__file__).resolve().parent.parent / "tests" / "data" / "retrieval_eval.json"
CUTOFFS = (5, 10)
COLUMNS = ("words", "meaning", "merged")
KEYS = ("by_word", "by_meaning", "merged")


def corpus() -> tuple[list[str], list[str]]:
    """The catalogue as the index holds it, built by the same code that builds the index.

    Measuring anything else measures a corpus nobody searches.
    """
    with SessionLocal() as db:
        products = repository.summarize(db, db.query(Product).order_by(Product.sku).all())

    cards = build_cards([product.model_dump() for product in products])
    return [card.sku for card in cards], [card.text for card in cards]


def current() -> tuple[dict, dict]:
    """Price and total stock per SKU. The service reads these over HTTP; here they are read
    straight from the database, so the measurement needs nothing running."""
    with SessionLocal() as db:
        prices = {row.sku: row.amount for row in db.query(Price).all()}
        stock: dict[str, int] = {}
        for row in db.query(Stock).all():
            stock[row.sku] = stock.get(row.sku, 0) + row.quantity

    return prices, stock


def recall(found: list[str], expected: list[str], at: int) -> float:
    """The share of the products that should have come back which did, inside the top `at`."""
    hit = set(found[:at]) & set(expected)
    return len(hit) / len(expected)


def scorable(asked: CustomerRequirements) -> None:
    """Refuse what `candidates` cannot answer, rather than score the order it came back in.

    A request ordered on price leaves `candidates` eligible but unsorted, because the price
    is not in the index. Only `search` can order it, and neither tool calls `search`.
    """
    if asked.order is not None and asked.order.key == PRICE:
        sys.exit(f"{asked.request!r} is ordered on price, which only search() can answer")


def reachable() -> bool:
    """Whether the index can be searched at all, asked once rather than per request."""
    try:
        retriever.candidates(CustomerRequirements(request="καλώδιο"), limit=1)
    except (retriever.IndexNotBuilt, embeddings.EmbeddingsUnavailable) as exc:
        logger.info("only the words can be measured — %s", exc)
        return False

    return True


def rankings(case: dict, corpus_: tuple, whole: bool, constrained: bool, held: tuple) -> tuple:
    """One ordering per column for one request, and whether the range decided it."""
    asked = CustomerRequirements(
        request=case["request"], **(case["requirements"] if constrained else {})
    )
    if not whole:
        return {"words": lexical.ranked(asked.request, *corpus_)}, False

    scorable(asked)
    _, trace = retriever.candidates(asked, limit=retriever.CANDIDATES)
    if "ordered_by" in trace:
        found = dict.fromkeys(COLUMNS, list(trace["merged"]))
    else:
        found = {name: list(trace.get(key, [])) for name, key in zip(COLUMNS, KEYS, strict=True)}

    return {name: affordable(codes, asked, held) for name, codes in found.items()}, (
        "ordered_by" in trace
    )


def affordable(codes: list[str], asked: CustomerRequirements, held: tuple) -> list[str]:
    """What the request's budget and its urgency leave, in the order the ranking put them."""
    prices, stock = held
    if asked.price_max is not None:
        codes = [c for c in codes if prices.get(c) is not None and prices[c] <= asked.price_max]
    if asked.immediate and asked.quantity:
        codes = [c for c in codes if stock.get(c, 0) >= asked.quantity]

    return codes


def table(title: str, cases: list, corpus_: tuple, whole: bool, constrained: bool, held: tuple):
    columns = COLUMNS if whole else COLUMNS[:1]
    totals = {(name, at): 0.0 for name in columns for at in CUTOFFS}

    logger.info("")
    logger.info("%s", title)
    logger.info("%-28s" + " %-12s" * len(columns), "request", *columns)
    logger.info("%-28s" + " %-12s" * len(columns), "", *["@5   @10"] * len(columns))

    sorted_any = False
    for case in cases:
        found, by_range = rankings(case, corpus_, whole, constrained, held)
        sorted_any = sorted_any or by_range
        scored = {
            (name, at): recall(found[name], case["expected"], at)
            for name in columns
            for at in CUTOFFS
        }
        for key, value in scored.items():
            totals[key] += value

        logger.info(
            "%-28s" + " %-12s" * len(columns),
            case["id"] + (" *" if by_range else ""),
            *[_pair(scored, name) for name in columns],
        )

    means = {key: value / len(cases) for key, value in totals.items()}
    logger.info(
        "%-28s" + " %-12s" * len(columns), "MEAN", *[_pair(means, name) for name in columns]
    )
    if sorted_any:
        logger.info("* answered by sorting the range, so neither ranking was asked")


def run() -> None:
    cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))["cases"]
    corpus_ = corpus()
    held = current()
    whole = reachable()

    logger.info("%d products, %d requests", len(corpus_[0]), len(cases))
    table("the ranking alone", cases, corpus_, whole, False, held)
    if whole:
        table("the constraints and the ranking together", cases, corpus_, whole, True, held)


def _pair(scored: dict, name: str) -> str:
    return " ".join(f"{scored[(name, at)]:<4.0%}" for at in CUTOFFS)


if __name__ == "__main__":
    run()
