"""
Indexing
========
Reads the catalogue and writes one card per product into the `products` collection.

The index is rebuilt whole: the catalogue is small enough that working out what changed
would cost more than rebuilding it. The vectors are a different matter — those are asked
for only when a card is new or has been rewritten, and the rest come off the file.
"""

import logging

from services.config import settings
from services.offer_service.clients import catalog
from services.offer_service.rag import documents, embeddings, store, vectors

logger = logging.getLogger(__name__)

PURPOSE = "product-cards"

BATCH = 100


def rebuild_products() -> dict:
    """Read the catalogue, write one card per product into the `products` collection.

    Returns:
        What was indexed: how many products, how many carry a distinguishing line, how
        many cards had to be embedded and how many came off the file.
    """
    products = catalog.fetch_all()
    if not products:
        logger.warning("the catalogue returned no products — nothing to index")
        return {"products": 0, "with_context": 0, "embedded": 0, "reused": 0}

    cards = documents.build_cards(products)
    held = vectors.load()
    wanted = [card for card in cards if _changed(card, held)]

    if wanted:
        logger.info("embedding %d cards with %s", len(wanted), settings.embedding_model)
        fresh = embeddings.embed([card.text for card in wanted], PURPOSE)
        for card, vector in zip(wanted, fresh, strict=True):
            held[card.sku] = vectors.entry(card.text, vector)

    # The file describes the catalogue as it stands, not everything it has ever held.
    kept = {card.sku: held[card.sku] for card in cards}
    if wanted or set(kept) != set(held):
        vectors.save(kept)

    collection = store.replace(store.PRODUCTS)
    for start in range(0, len(cards), BATCH):
        batch = cards[start : start + BATCH]
        collection.add(
            ids=[card.sku for card in batch],
            documents=[card.text for card in batch],
            metadatas=[card.metadata for card in batch],
            embeddings=[kept[card.sku][1] for card in batch],
        )

    report = {
        "products": len(cards),
        "with_context": sum(1 for card in cards if documents.CONTEXT_PREFIX in card.text),
        "embedded": len(wanted),
        "reused": len(cards) - len(wanted),
    }
    logger.info(
        "indexed %(products)d products — %(embedded)d embedded, %(reused)d off the file",
        report,
    )
    return report


def _changed(card: documents.Card, held: dict) -> bool:
    mark, _ = held.get(card.sku, ("", None))
    return mark != vectors.digest(card.text)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        rebuild_products()
    except (catalog.CatalogueUnavailable, embeddings.EmbeddingsUnavailable) as exc:
        raise SystemExit(f"the index was not built: {exc}") from exc
