"""
Embedded cards, kept
====================
The vectors the embedding model produced for our cards, stored in version control next
to the catalogue they describe.

They are here for the same reason the shop texts are: they were paid for, and nothing
reproduces them for free. The index built on top of them is a different matter — that is
derived, and rebuilding it costs seconds.

Each vector is filed under its SKU with a digest of the card it came from, so a card that
has been rewritten is embedded again and every other card is not.
"""

import logging
from hashlib import blake2b
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).resolve().parents[3] / "data" / "raw" / "card_vectors.npz"


def digest(text: str) -> str:
    """What a card has to still be for its vector to still apply."""
    return blake2b(text.encode("utf-8"), digest_size=12).hexdigest()


def entry(text: str, vector) -> tuple[str, np.ndarray]:
    """One card's vector as the file holds it."""
    return digest(text), np.asarray(vector, dtype=np.float32)


def load() -> dict[str, tuple[str, np.ndarray]]:
    """Every vector on file, keyed by SKU, with the digest of the card it came from."""
    if not CACHE_FILE.exists():
        logger.info("no vectors on file at %s", CACHE_FILE)
        return {}

    held = np.load(CACHE_FILE, allow_pickle=False)
    stored = dict(
        zip(
            (str(sku) for sku in held["skus"]),
            zip((str(mark) for mark in held["digests"]), held["vectors"], strict=True),
            strict=True,
        )
    )
    logger.info("%d vectors read from %s", len(stored), CACHE_FILE.name)
    return stored


def save(entries: dict[str, tuple[str, np.ndarray]]) -> None:
    """Write the vectors back, in SKU order so the file does not churn."""
    skus = sorted(entries)
    np.savez_compressed(
        CACHE_FILE,
        skus=np.array(skus),
        digests=np.array([entries[sku][0] for sku in skus]),
        vectors=np.array([entries[sku][1] for sku in skus], dtype=np.float32),
    )
    logger.info("%d vectors written to %s", len(skus), CACHE_FILE.name)
