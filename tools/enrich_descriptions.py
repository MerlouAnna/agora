"""
Shop texts from the model
=========================
Fills the `web_description` of every product in data/raw/catalog.json that still has none.
The terse ERP line and the specifications read out of it go to the model, which writes the
paragraph a shop would show, and the same validator the generation endpoint uses decides
whether it is usable.

Only products with no text yet are sent, and the file is written after every batch, so an
interrupted run can be started again without paying twice for what already worked.

Run from the repository root:  python -m tools.enrich_descriptions
                               python -m tools.enrich_descriptions --limit 10
"""

import argparse
import json
import logging

from services import config
from services.data_service.generation import descriptions
from services.data_service.ingestion.loader import CATALOG_FILE, load_catalog
from tools.check_descriptions import products, shop_texts

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BATCH = 10


def run(limit: int | None = None, batch: int = BATCH) -> None:
    catalogue = products()
    written = shop_texts()

    items = [
        {"sku": sku, **product}
        for sku, product in catalogue.items()
        if sku not in written
    ]
    logger.info("%d products without a shop text", len(items))

    if limit is not None:
        items = items[:limit]
        logger.info("stopping after %d of them", len(items))

    if not items:
        return

    config.openai_client(descriptions.ModelUnavailable)
    refused: list[str] = []

    for start in range(0, len(items), batch):
        chunk = items[start : start + batch]
        logger.info("asking for %d–%d of %d", start + 1, start + len(chunk), len(items))

        outcome = descriptions.write(chunk)
        _save(outcome.texts)
        refused.extend(outcome.rejected)

        logger.info(
            "   %d written, %d refused, %d rounds — saved",
            len(outcome.texts),
            len(outcome.rejected),
            outcome.rounds_used,
        )

    logger.info("%d refused in total", len(refused))
    for sku in refused:
        logger.info("   refused %s", sku)


def _save(texts: dict[str, str]) -> None:
    """Write straight back into the catalogue, so an interrupted run keeps its work."""
    catalog = load_catalog()

    for record in catalog["products"]:
        if record["sku"] in texts:
            record["web_description"] = texts[record["sku"]]

    CATALOG_FILE.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Stop after this many products.")
    parser.add_argument("--batch", type=int, default=BATCH, help="Products per call.")
    args = parser.parse_args()

    run(limit=args.limit, batch=args.batch)


if __name__ == "__main__":
    main()
