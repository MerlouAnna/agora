"""
Description check
=================
Runs the validator the generation endpoint runs, over every shop text in
data/raw/catalog.json. No model and no network: the specifications are read out of each
product's ERP line, and the shop text has to give every one of them back.

It also measures how much two descriptions overlap in wording. These texts are going into
a vector index, and two products whose descriptions differ only in a number will not be
told apart by it — so a pair that shares most of its phrasing is a defect even when every
specification in it is correct.

Run from the repository root:  python -m tools.check_descriptions

Exits non-zero when something is wrong, so it can gate a commit.
"""

import json
import logging
import re
import sys
from itertools import combinations

from services.data_service.categories import Category
from services.data_service.generation import validator
from services.data_service.ingestion.loader import CATALOG_FILE, load_catalog
from services.data_service.ingestion.parsers import extract_specs, normalize_sku

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Share of three-word runs two descriptions have in common.
TOO_CLOSE = 0.65
WATCH = 0.45


def products() -> dict[str, dict]:
    """Every product the catalogue names, with the specs its ERP line carries."""
    found: dict[str, dict] = {}

    for record in load_catalog()["products"]:
        sku = normalize_sku(record.get("sku", ""))
        if sku is None or sku in found:
            continue

        category = Category(record["category"])
        line = record["description"].strip()
        found[sku] = {
            "category": category,
            "brand": record["brand"],
            "erp": line,
            "specs": extract_specs(category, line),
        }

    return found


def shop_texts() -> dict[str, str]:
    """What is written for each product, skipping the ones still waiting."""
    return {
        record["sku"]: record["web_description"].strip()
        for record in load_catalog()["products"]
        if record.get("web_description", "").strip()
    }


def run() -> int:
    catalogue = products()
    texts = shop_texts()

    missing = sorted(set(catalogue) - set(texts))
    unknown = sorted(set(texts) - set(catalogue))
    failed: list[tuple[str, str]] = []
    duplicates: dict[str, list[str]] = {}

    for sku, text in texts.items():
        if sku not in catalogue:
            continue

        product = catalogue[sku]
        problem = validator.check(product["category"], product["specs"], text)
        if problem is not None:
            failed.append((sku, problem))

        duplicates.setdefault(" ".join(text.split()), []).append(sku)

    repeated = {text: skus for text, skus in duplicates.items() if len(skus) > 1}
    close = overlaps(texts)
    too_close = [pair for pair in close if pair[0] >= TOO_CLOSE]

    logger.info("%d products, %d shop texts", len(catalogue), len(texts))
    logger.info("%d usable", len(texts) - len(failed) - len(unknown))

    for sku, problem in failed:
        logger.info("   FAILED  %s — %s", sku, problem)
    for sku in unknown:
        logger.info("   UNKNOWN %s — no such product", sku)
    for skus in repeated.values():
        logger.info("   REPEATED %s share the same text", ", ".join(skus))

    if close:
        logger.info("%d pairs share %.0f%% of their wording or more:", len(close), WATCH * 100)
        for score, first, second in close[:15]:
            mark = "TOO CLOSE" if score >= TOO_CLOSE else "close    "
            logger.info("   %s %.0f%%  %s / %s", mark, score * 100, first, second)
            logger.info("      %s", texts[first])
            logger.info("      %s", texts[second])

    if missing:
        logger.info("   %d products still have no text", len(missing))
        logger.info("   %s", " ".join(missing))

    return 1 if failed or unknown or repeated or too_close else 0


def overlaps(texts: dict[str, str]) -> list[tuple[float, str, str]]:
    """Pairs of descriptions that reuse each other's phrasing, worst first."""
    runs = {sku: _runs(text) for sku, text in texts.items()}
    found = []

    for first, second in combinations(sorted(runs), 2):
        a, b = runs[first], runs[second]
        if not a or not b:
            continue
        score = len(a & b) / min(len(a), len(b))
        if score >= WATCH:
            found.append((score, first, second))

    return sorted(found, reverse=True)


def _runs(text: str) -> set[str]:
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return {" ".join(words[i : i + 3]) for i in range(len(words) - 2)}


if __name__ == "__main__":
    sys.exit(run())
