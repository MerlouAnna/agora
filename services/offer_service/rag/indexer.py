"""
Indexing
========
Reads the catalogue and the business documents and writes both collections. A collection
is rebuilt whole; a vector is asked for only when its text is new or has been rewritten.
"""

import logging
from pathlib import Path

from services.config import settings
from services.offer_service.clients import catalog
from services.offer_service.rag import documents, embeddings, policies, store, vectors

logger = logging.getLogger(__name__)

PRODUCTS = "product-cards"
POLICIES = "policy-passages"

BATCH = 100


def rebuild_products() -> dict:
    """Read the catalogue, write one card per product into the `products` collection.

    Returns:
        How many products, how many carry a distinguishing line, and how many cards had
        to be embedded rather than read off the file.
    """
    products = catalog.fetch_all()
    if not products:
        store.replace(store.PRODUCTS)
        logger.warning("the catalogue returned no products — the collection was emptied")
        return {"products": 0, "with_context": 0, "embedded": 0, "reused": 0}

    cards = documents.build_cards(products)
    skus = [card.sku for card in cards]
    texts = [card.text for card in cards]
    held, embedded = _vectors(skus, texts, vectors.PRODUCT_FILE, PRODUCTS)

    _fill(
        store.replace(store.PRODUCTS),
        skus,
        texts,
        [card.metadata for card in cards],
        held,
    )

    report = {
        "products": len(cards),
        "with_context": sum(1 for card in cards if documents.CONTEXT_PREFIX in card.text),
        "embedded": embedded,
        "reused": len(cards) - embedded,
    }
    logger.info(
        "products: %(products)d indexed — %(embedded)d embedded, %(reused)d off the file",
        report,
    )
    return report


def rebuild_policies(folder: Path | None = None) -> dict:
    """Read the business documents, write one passage per section into `policies`.

    Returns:
        How many documents and passages, and how many passages had to be embedded.
    """
    passages = policies.read_all(folder)
    if not passages:
        store.replace(store.POLICIES)
        logger.warning(
            "no readable documents in %s — the collection was emptied",
            folder or policies.DOCS_DIR,
        )
        return {"documents": 0, "passages": 0, "embedded": 0, "reused": 0}

    codes = [passage.id for passage in passages]
    texts = [passage.text for passage in passages]
    held, embedded = _vectors(codes, texts, vectors.POLICY_FILE, POLICIES)

    _fill(
        store.replace(store.POLICIES),
        codes,
        texts,
        [passage.metadata for passage in passages],
        held,
    )

    report = {
        "documents": len({passage.metadata["document"] for passage in passages}),
        "passages": len(passages),
        "embedded": embedded,
        "reused": len(passages) - embedded,
    }
    logger.info(
        "policies: %(passages)d passages from %(documents)d documents — "
        "%(embedded)d embedded, %(reused)d off the file",
        report,
    )
    return report


def _vectors(codes: list[str], texts: list[str], path: Path, purpose: str) -> tuple[dict, int]:
    """The vectors for these texts, asking the model only for the ones not already on file."""
    held = vectors.load(path)
    wanted = [
        n
        for n, code in enumerate(codes)
        if held.get(code, ("", None))[0] != vectors.digest(texts[n])
    ]

    if wanted:
        logger.info("embedding %d of %d with %s", len(wanted), len(codes), settings.embedding_model)
        fresh = embeddings.embed([texts[n] for n in wanted], purpose)
        for n, vector in zip(wanted, fresh, strict=True):
            held[codes[n]] = vectors.entry(texts[n], vector)

    # The file describes what there is now, not everything there has ever been.
    kept = {code: held[code] for code in codes}
    if wanted or set(kept) != set(held):
        vectors.save(kept, path)

    return kept, len(wanted)


def _fill(collection, codes: list[str], texts: list[str], metadata: list[dict], held: dict) -> None:
    for start in range(0, len(codes), BATCH):
        stop = start + BATCH
        collection.add(
            ids=codes[start:stop],
            documents=texts[start:stop],
            metadatas=metadata[start:stop],
            embeddings=[held[code][1] for code in codes[start:stop]],
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        rebuild_products()
        rebuild_policies()
    except (catalog.CatalogueUnavailable, embeddings.EmbeddingsUnavailable) as exc:
        raise SystemExit(f"the index was not built: {exc}") from exc
