"""
Embedded texts, kept
====================
The vectors the embedding model produced — one file for the product cards, one for the
passages of the business documents — stored in version control beside the catalogue and
the documents they describe.

They are here for the same reason the shop texts are: they were paid for, and nothing
reproduces them for free. The index built on top of them is a different matter — that is
derived, and rebuilding it costs seconds.

Each vector is filed under its own code — a SKU, or a document and section — with a digest
of the text it came from, so a text that has been rewritten is embedded again and every
other one is not.
"""

import logging
from hashlib import blake2b
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

RAW = Path(__file__).resolve().parents[3] / "data" / "raw"
PRODUCT_FILE = RAW / "card_vectors.npz"
POLICY_FILE = RAW / "policy_vectors.npz"


def digest(text: str) -> str:
    """What a text has to still be for its vector to still apply."""
    return blake2b(text.encode("utf-8"), digest_size=12).hexdigest()


def entry(text: str, vector) -> tuple[str, np.ndarray]:
    """One vector as the file holds it, beside the digest of the text behind it."""
    return digest(text), np.asarray(vector, dtype=np.float32)


def load(path: Path) -> dict[str, tuple[str, np.ndarray]]:
    """Every vector on file, keyed by its own code, with the digest of the text it came from."""
    if not path.exists():
        logger.info("no vectors on file at %s", path)
        return {}

    held = np.load(path, allow_pickle=False)
    stored = dict(
        zip(
            (str(code) for code in held["codes"]),
            zip((str(mark) for mark in held["digests"]), held["vectors"], strict=True),
            strict=True,
        )
    )
    logger.info("%d vectors read from %s", len(stored), path.name)
    return stored


def save(entries: dict[str, tuple[str, np.ndarray]], path: Path) -> None:
    """Write the vectors back, in code order so the file does not churn."""
    codes = sorted(entries)
    np.savez_compressed(
        path,
        codes=np.array(codes),
        digests=np.array([entries[code][0] for code in codes]),
        vectors=np.array([entries[code][1] for code in codes], dtype=np.float32),
    )
    logger.info("%d vectors written to %s", len(codes), path.name)
