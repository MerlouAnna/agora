"""
Product cards
=============
The text that goes into the vector store, one card per SKU, and the metadata a search
filters on before it compares a single vector.

A card carries four things: the code and where the product sits in the catalogue, one
line saying what distinguishes it from the products around it, its specifications
written out in the tokens people actually type, and the shop text. Price and stock are
deliberately missing — both change without anything being reindexed, and an offer quoted
from a stale number is worse than no offer at all.
"""

from collections import defaultdict
from dataclasses import dataclass

from services.data_service.categories import Category, specs_for

# Above this share of the category, being the highest or the lowest says nothing: three
# cores is the smallest cable we sell and also what most of the shelf holds.
EXTREME_SHARE = 1 / 3
RARE_SHARE = 1 / 5

# What being at either end of a specification is called, in the gender the noun takes.
EXTREMES = {
    "cores": ("οι περισσότεροι αγωγοί", "οι λιγότεροι αγωγοί"),
    "section_mm": ("η μεγαλύτερη διατομή", "η μικρότερη διατομή"),
    "length_m": ("το μεγαλύτερο μήκος", "το μικρότερο μήκος"),
    "watt": ("η μεγαλύτερη ισχύς", "η μικρότερη ισχύς"),
    "va": ("η μεγαλύτερη ισχύς σε VA", "η μικρότερη ισχύς σε VA"),
    "autonomy_min": ("η μεγαλύτερη αυτονομία", "η μικρότερη αυτονομία"),
    "ports": ("οι περισσότερες θύρες", "οι λιγότερες θύρες"),
    "speed_mbps": ("η μεγαλύτερη ταχύτητα", "η μικρότερη ταχύτητα"),
    "amperage": ("η μεγαλύτερη ένταση", "η μικρότερη ένταση"),
}

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

CONTEXT_PREFIX = "Στην κατηγορία:"
MID_RANGE = "μεσαίες τιμές σε όλα τα χαρακτηριστικά"


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
    cohorts = _cohorts(products)
    return [
        Card(
            sku=product["sku"],
            text=card_text(product, cohorts[product["category"]]),
            metadata=metadata_for(product),
        )
        for product in products
    ]


def card_text(product: dict, cohort: dict[str, list]) -> str:
    """The lines that get embedded, for one product.

    A product that stands out nowhere gets no context line at all: the same sentence
    repeated across half the catalogue is a constant, and a constant tells a search
    nothing.
    """
    specs = product.get("specs") or {}
    context = context_line(specs, cohort)

    lines = [f"{product['sku']} · {product['category']} · {product['brand']}"]
    if context != MID_RANGE:
        lines.append(f"{CONTEXT_PREFIX} {context}.")
    lines += [
        spec_line(product["category"], specs),
        product["description"],
        product.get("web_description") or "",
    ]

    return "\n".join(line for line in lines if line)


def context_line(specs: dict, cohort: dict[str, list]) -> str:
    """Where this product's specifications sit among the products it competes with.

    Only the ends of a range and the values almost nobody else carries are worth saying;
    a product that is unremarkable everywhere is described as exactly that.
    """
    notes = []

    for key, value in specs.items():
        values = cohort.get(key) or []
        if len(set(values)) < 2:
            continue

        share = values.count(value) / len(values)

        if key in EXTREMES and share <= EXTREME_SHARE:
            high, low = EXTREMES[key]
            if value == max(values):
                notes.append(f"{high} στην κατηγορία ({measure(key, value)})")
            elif value == min(values):
                notes.append(f"{low} στην κατηγορία ({measure(key, value)})")
        elif key not in EXTREMES and share <= RARE_SHARE:
            notes.append(f"σπάνιο {value}, {values.count(value)} από {len(values)} προϊόντα")

    return " · ".join(notes) if notes else MID_RANGE


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
    """What the search filters on: the category, who supplies it, and every specification.

    Prices and stock are left out on purpose — they are read from the catalogue when an
    offer is built, so that no answer is ever assembled from a number the index happened
    to be holding.
    """
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


def _cohorts(products: list[dict]) -> dict[str, dict[str, list]]:
    """Every value each category holds for each specification."""
    cohorts: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    for product in products:
        for key, value in (product.get("specs") or {}).items():
            cohorts[product["category"]][key].append(value)

    return cohorts


def _true(value) -> bool:
    return str(value).strip().lower() == "true" if not isinstance(value, bool) else value


def _number(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
