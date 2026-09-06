"""
Retrieval measurement
=====================
Runs the requests in tests/data/retrieval_eval.json and reports how many of the products
that should have come back actually did, at three cut-offs.

The expected answers were computed with SQL against the catalogue, not chosen by eye, so
the number this prints is a fact about the retriever and not about anyone's judgement.

Run from the repository root:  python -m tools.measure_retrieval
"""

import json
import logging
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

from services.data_service import repository
from services.data_service.database import SessionLocal
from services.data_service.models import Product
from services.offer_service.rag.documents import build_cards

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EVAL_FILE = Path(__file__).resolve().parent.parent / "tests" / "data" / "retrieval_eval.json"
CUTOFFS = (1, 5, 10)

# Keep `3x2.5mm`, `s/ftp`, `cat6a` and `80+` in one piece: they are the tokens that matter.
WORD = re.compile(r"[\w./+]+")


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


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


def run() -> None:
    cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))["cases"]
    skus, documents = corpus()
    index = BM25Okapi([words(d) for d in documents])

    logger.info("%d products, %d requests", len(skus), len(cases))
    logger.info("")
    logger.info("%-28s %-6s %-6s %-6s  %s", "request", *[f"@{n}" for n in CUTOFFS], "trap")

    totals = {n: 0.0 for n in CUTOFFS}
    for case in cases:
        scores = index.get_scores(words(case["request"]))
        ordered = sorted(zip(skus, scores, strict=True), key=lambda pair: (-pair[1], pair[0]))
        ranked = [sku for sku, _ in ordered]
        scored = {n: recall(ranked, case["expected"], n) for n in CUTOFFS}

        for n in CUTOFFS:
            totals[n] += scored[n]
        logger.info(
            "%-28s %-6s %-6s %-6s  %s",
            case["id"],
            *[f"{scored[n]:.0%}" for n in CUTOFFS],
            case["trap"][:44],
        )

    logger.info("")
    logger.info(
        "%-28s %-6s %-6s %-6s",
        "MEAN",
        *[f"{totals[n] / len(cases):.0%}" for n in CUTOFFS],
    )


if __name__ == "__main__":
    run()
