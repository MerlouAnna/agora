"""
Indexing
========
Building the collections: product cards from the catalogue, business documents from
`data/docs`.

Both are rebuilt whole. The catalogue is small enough that working out what changed would
cost more than embedding everything again, and a stale card is a product the salesperson
is offered after it has been withdrawn.
"""

import logging

from services.config import settings
from services.offer_service.clients import catalog
from services.offer_service.rag import documents, embeddings, store

logger = logging.getLogger(__name__)

PURPOSE = "product-cards"

BATCH = 100


def rebuild_products() -> dict:
    """Read the catalogue, write one card per product into the `products` collection.

    Returns:
        What was indexed: how many products, how many carry a distinguishing line, and
        the size of the text that was embedded.
    """
    products = catalog.fetch_all()
    if not products:
        logger.warning("the catalogue returned no products — nothing to index")
        return {"products": 0, "with_context": 0, "characters": 0}

    cards = documents.build_cards(products)
    logger.info("embedding %d cards with %s", len(cards), settings.embedding_model)
    vectors = embeddings.embed([card.text for card in cards], PURPOSE)

    collection = store.replace(store.PRODUCTS)
    for start in range(0, len(cards), BATCH):
        batch = cards[start : start + BATCH]
        collection.add(
            ids=[card.sku for card in batch],
            documents=[card.text for card in batch],
            metadatas=[card.metadata for card in batch],
            embeddings=vectors[start : start + BATCH],
        )

    report = {
        "products": len(cards),
        "with_context": sum(1 for card in cards if documents.CONTEXT_PREFIX in card.text),
        "characters": sum(len(card.text) for card in cards),
    }
    logger.info(
        "indexed %(products)d products, %(with_context)d with a distinguishing line", report
    )
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    rebuild_products()
