"""
Retrieval measurement
=====================
Runs the requests in tests/data/retrieval_eval.json and reports how many of the products
that should have come back actually did, at two cut-offs, for each half of the search and
for the two of them fused.

The expected answers were computed with SQL against the catalogue, not chosen by eye, so
the number this prints is a fact about the retriever and not about anyone's judgement.
No constraints are applied: this measures the ranking, and the filter is measured apart.

Run from the repository root:  python -m tools.measure_retrieval
"""

import json
import logging
from pathlib import Path

from services.data_service import repository
from services.data_service.database import SessionLocal
from services.data_service.models import Product
from services.offer_service.rag import embeddings, lexical, retriever
from services.offer_service.rag.documents import build_cards
from services.offer_service.requirements import CustomerRequirements

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EVAL_FILE = Path(__file__).resolve().parent.parent / "tests" / "data" / "retrieval_eval.json"
CUTOFFS = (5, 10)
COLUMNS = ("words", "meaning", "fused")


def corpus() -> tuple[list[str], list[str]]:
    """The catalogue as the index holds it, built by the same code that builds the index.

    Measuring anything else measures a corpus nobody searches.
    """
    with SessionLocal() as db:
        products = repository.summarize(db, db.query(Product).order_by(Product.sku).all())

    cards = build_cards([product.model_dump() for product in products])
    return [card.sku for card in cards], [card.text for card in cards]


def recall(found: list[str], expected: list[str], at: int) -> float:
    """The share of the products that should have come back which did, inside the top `at`."""
    hit = set(found[:at]) & set(expected)
    return len(hit) / len(expected)


def rankings(request: str, skus: list[str], documents: list[str], whole: bool) -> dict:
    """One ordering per column, from the index when it can be reached and BM25 when not."""
    if not whole:
        return {"words": lexical.ranked(request, skus, documents)}

    _, trace = retriever.candidates(CustomerRequirements(request=request), limit=max(CUTOFFS))
    keys = ("by_word", "by_meaning", "fused")
    return {name: trace[key] for name, key in zip(COLUMNS, keys, strict=True)}


def reachable() -> bool:
    """Whether the meaning side can be measured at all, asked once rather than per request."""
    try:
        retriever.candidates(CustomerRequirements(request="καλώδιο"), limit=1)
    except (retriever.IndexNotBuilt, embeddings.EmbeddingsUnavailable) as exc:
        logger.info("the meaning side is not being measured — %s", exc)
        return False

    return True


def run() -> None:
    cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))["cases"]
    skus, documents = corpus()
    whole = reachable()
    columns = COLUMNS if whole else COLUMNS[:1]

    logger.info("%d products, %d requests", len(skus), len(cases))
    logger.info("")
    logger.info("%-28s" + " %-12s" * len(columns), "request", *columns)
    logger.info("%-28s" + " %-12s" * len(columns), "", *["@5   @10"] * len(columns))

    totals = {(name, at): 0.0 for name in columns for at in CUTOFFS}
    for case in cases:
        found = rankings(case["request"], skus, documents, whole)
        scored = {
            (name, at): recall(found[name], case["expected"], at)
            for name in columns
            for at in CUTOFFS
        }
        for key, value in scored.items():
            totals[key] += value

        logger.info(
            "%-28s" + " %-12s" * len(columns),
            case["id"],
            *[_pair(scored, name) for name in columns],
        )

    logger.info("")
    logger.info(
        "%-28s" + " %-12s" * len(columns),
        "MEAN",
        *[_pair({k: v / len(cases) for k, v in totals.items()}, name) for name in columns],
    )


def _pair(scored: dict, name: str) -> str:
    return " ".join(f"{scored[(name, at)]:<4.0%}" for at in CUTOFFS)


if __name__ == "__main__":
    run()
