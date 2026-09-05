"""
Mock data generator
===================
Builds `data/raw/catalog.json`, the catalogue as the reseller's systems agree on it: one
object per SKU with its specifications inside the ERP line, its price, the warehouses that
hold it and the supplier behind it, plus the supplier registry.

What a product of each category looks like is decided by the record builder in the
catalogue service; this script only decides how many of each there are and what the seed
draws for them. Every value comes from one seed, so the file can be regenerated exactly.

The e-shop text is the one thing no seed can produce, so a re-run carries over whatever is
already written for a SKU rather than throwing it away.

Run from the repository root:  python -m tools.generate_mock_data
"""

import json
import logging
import random
from pathlib import Path

from services.data_service.categories import (
    SKU_PREFIXES,
    Category,
    SupplierCode,
    Warehouse,
)
from services.data_service.generation.builder import (
    DEFAULT_BRANDS,
    QUANTITIES,
    SKU_START,
    build_specs,
    describe,
    price_for,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SEED = 20260905
CATALOG_FILE = Path(__file__).resolve().parent.parent / "data" / "raw" / "catalog.json"

UPDATED_DATES = ["2026-07-14", "2026-08-03", "2026-08-21", "2026-09-01"]

SUPPLIERS = [
    (SupplierCode.SUP_01, "Ionia Electric", 3, 0.96),
    (SupplierCode.SUP_02, "Aegean Supplies", 7, 0.88),
    (SupplierCode.SUP_03, "Balkan Cables", 14, 0.74),
    (SupplierCode.SUP_04, "Hellenic Power Systems", 5, 0.92),
]

# 226 SKUs in total (small enough that the file can still be read by the eye)
CATEGORY_SIZES = {
    Category.POWER: 58,
    Category.DATA: 46,
    Category.PSU: 34,
    Category.UPS: 28,
    Category.NETWORK: 30,
    Category.CONNECTORS: 30,
}

# The warehouse system has never heard of these, so their stock is unknown rather than zero.
UNREGISTERED = (3, 61, 104, 158, 199)


def build_catalog(rng: random.Random) -> list[dict]:
    """Build the whole product catalogue.

    Args:
        rng: Seeded generator, so the same seed gives the same catalogue.

    Returns:
        One dict per SKU, carrying the identifiers, the Greek ERP line and the commercial
        fields, ready to be written out.
    """
    drawn = []
    for category, size in CATEGORY_SIZES.items():
        for n in range(size):
            specs = build_specs(category, rng)
            # The order of these draws is the catalogue's identity: change it and every
            # product downstream of the change becomes a different product.
            drawn.append(
                (
                    f"{SKU_PREFIXES[category]}-{SKU_START + n}",
                    str(category),
                    rng.choice(DEFAULT_BRANDS),
                    describe(category, specs, rng),
                    price_for(category, rng),
                    rng.choice(QUANTITIES),
                    str(rng.choice(list(Warehouse))),
                    str(rng.choice(SUPPLIERS)[0]),
                )
            )

    catalog = []
    for index, (sku, category, brand, line, price, quantity, warehouse, supplier) in enumerate(drawn):
        catalog.append(
            {
                "sku": sku,
                "category": category,
                "brand": brand,
                "unit": "ΤΕΜ",
                "description": line,
                "web_description": "",
                "price": price,
                "currency": "EUR",
                "price_updated_at": rng.choice(UPDATED_DATES),
                "supplier": supplier,
                "stock": []
                if index in UNREGISTERED
                else [{"warehouse": warehouse, "quantity": quantity}],
            }
        )

    return catalog


def shop_texts() -> dict[str, str]:
    """The e-shop texts already written, keyed by SKU."""
    if not CATALOG_FILE.exists():
        return {}

    with open(CATALOG_FILE, encoding="utf-8") as f:
        return {
            product["sku"]: product["web_description"]
            for product in json.load(f)["products"]
            if product.get("web_description", "").strip()
        }


def write(catalog: list[dict]) -> None:
    written = shop_texts()
    for product in catalog:
        product["web_description"] = written.get(product["sku"], "")

    registry = [
        {
            "code": str(code),
            "name": name,
            "lead_time_days": lead_time,
            "reliability_score": reliability,
        }
        for code, name, lead_time, reliability in SUPPLIERS
    ]

    CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CATALOG_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"suppliers": registry, "products": catalog}, f, ensure_ascii=False, indent=2
        )
        f.write("\n")

    logger.info(
        "catalog.json — %d products, %d with shop text, %d without a stock record",
        len(catalog),
        sum(1 for p in catalog if p["web_description"]),
        sum(1 for p in catalog if not p["stock"]),
    )


def main() -> None:
    rng = random.Random(SEED)
    catalog = build_catalog(rng)
    logger.info(
        "catalogue built — %d SKUs over %d categories", len(catalog), len(CATEGORY_SIZES)
    )
    write(catalog)


if __name__ == "__main__":
    main()
