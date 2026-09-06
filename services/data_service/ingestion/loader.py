"""
Loader
======
Reads what the sources hand over, exactly as they hand it over. Nothing is cleaned,
converted or rejected here.

There are two of them. `catalog.json` is the catalogue the reseller's systems agree on and
comes in structured. Everything else arrives as a CSV somebody exported — from the
generation endpoint or from a partner's feed — and comes in as strings.
"""

import csv
import io
import json
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "raw"
CATALOG_FILE = RAW_DIR / "catalog.json"


def load_catalog() -> dict:
    """The whole catalogue: the supplier registry and one record per SKU."""
    with open(CATALOG_FILE, encoding="utf-8") as f:
        return json.load(f)


ENCODINGS = ("utf-8-sig", "cp1253", "cp1252", "latin-1")
SEPARATORS = (",", ";", "\t")


def read_rows(text: str, delimiter: str | None = None) -> list[dict]:
    """A CSV that arrived as text, one dict per row, every value still a string."""
    return list(
        csv.DictReader(io.StringIO(text), delimiter=delimiter or _separator(text))
    )


def read_upload(raw: bytes) -> list[dict]:
    """A CSV somebody attached, without asking them how they saved it.

    A spreadsheet saved on a Greek Windows machine is Windows-1253 with semicolons, not
    UTF-8 with commas, and refusing it would only mean asking the sender to do the work.

    Raises:
        ValueError: The bytes are not a CSV at all.
    """
    try:
        return read_rows(_decode(raw))
    except csv.Error as exc:
        raise ValueError(f"this does not read as a CSV: {exc}") from exc


def _decode(raw: bytes) -> str:
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise ValueError("the file is not text in any encoding we read")


def _separator(text: str) -> str:
    """Whichever separator the heading line uses the most."""
    heading = text.splitlines()[0] if text else ""
    return max(SEPARATORS, key=heading.count)
