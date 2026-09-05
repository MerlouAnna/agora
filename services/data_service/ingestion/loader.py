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


def read_rows(text: str, delimiter: str = ",") -> list[dict]:
    """A CSV that arrived as text, one dict per row, every value still a string."""
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
