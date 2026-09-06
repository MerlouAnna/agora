"""
Product cards
=============
The text that goes into the vector store, one card per SKU, and the metadata a search
filters on. Never the price or the stock: both change without anything being reindexed.
"""

from dataclasses import dataclass

from services.data_service.categories import Category, specs_for

UNITS = {
    "cores": "{} αγωγοί",
    "section_mm": "{}mm",
    "length_m": "{} μ.",
    "watt": "{}W",
    "va": "{}VA",
    "autonomy_min": "{} λεπτά",
    "ports": "{} θύρες",
    "speed_mbps": "{}Mbps",
    "amperage": "{}A",
}

NOUNS = {"section_mm": "διατομή", "length_m": "μήκος", "autonomy_min": "αυτονομία"}

FLAGS = {"poe": ("PoE", None), "managed": ("managed", "unmanaged")}


@dataclass(frozen=True)
class Card:
    """One product as the vector store holds it."""

    sku: str
    text: str
    metadata: dict


def build_cards(products: list[dict]) -> list[Card]:
    """Turn catalogue records into cards, reading each product against its own category.

    Args:
        products: Catalogue records as the products API returns them.

    Returns:
        One card per product, in the order given.
    """
    return [
        Card(sku=product["sku"], text=card_text(product), metadata=metadata_for(product))
        for product in products
    ]


def card_text(product: dict) -> str:
    """The lines that get embedded, for one product."""
    lines = [
        f"{product['sku']} · {product['category']} · {product['brand']}",
        spec_line(product["category"], product.get("specs") or {}),
        product["description"],
        product.get("web_description") or "",
    ]

    return "\n".join(line for line in lines if line)


def spec_line(category: str, specs: dict) -> str:
    """Every specification on one line, each written the way it is typed into a search."""
    written = []
    for key in specs_for(Category(category)):
        if key not in specs:
            continue
        value = measure(key, specs[key])
        if value:
            written.append(f"{NOUNS[key]} {value}" if key in NOUNS else value)

    return " · ".join(written)


def measure(key: str, value) -> str | None:
    """One specification as text, or nothing when the value is a flag that is switched off."""
    if key in FLAGS:
        on, off = FLAGS[key]
        return on if _true(value) else off
    if key in UNITS:
        return UNITS[key].format(_number(value))
    return str(value)


def metadata_for(product: dict) -> dict:
    """What the search filters on: the category, who supplies it, and every specification."""
    metadata = {
        "sku": product["sku"],
        "category": product["category"],
        "brand": product["brand"],
    }
    if product.get("supplier_code"):
        metadata["supplier_code"] = product["supplier_code"]

    for key, value in (product.get("specs") or {}).items():
        metadata[key] = _true(value) if key in FLAGS else value

    return metadata


def _true(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _number(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
