"""
Loader
======
Reads the four raw exports exactly as they are. Nothing is cleaned, converted or
rejected here — every value comes back as the string the source system wrote.
"""

import csv
import json
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "raw"


def load_erp() -> list[dict]:
    return _read_csv(RAW_DIR / "erp_products.csv")


def load_stock() -> list[dict]:
    return _read_csv(RAW_DIR / "wms_stock.csv", delimiter=";")


def load_pricing() -> list[dict]:
    return _read_csv(RAW_DIR / "pricing.csv")


def load_suppliers() -> list[dict]:
    """The supplier file is nested JSON: each supplier carries the SKUs it supplies."""
    with open(RAW_DIR / "suppliers.json", encoding="utf-8") as f:
        return json.load(f)["suppliers"]


def _read_csv(path: Path, delimiter: str = ",") -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=delimiter))
