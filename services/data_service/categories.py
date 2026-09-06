"""
Category registry
=================
The catalogue taxonomy in one place: the categories themselves, the specs each one
carries, whether a spec is a number or a label, and the price band its products sit in.
The generator, the API schemas and the UI all read from here.
"""

from enum import StrEnum


class Category(StrEnum):
    """The catalogue categories. The value is what gets stored and what the API accepts."""

    POWER = "POWER"
    DATA = "DATA"
    PSU = "PSU"
    UPS = "UPS"
    NETWORK = "NETWORK"
    CONNECTORS = "CONNECTORS"


class Warehouse(StrEnum):
    """The stock locations. The same codes appear in the delivery terms document."""

    ATH_01 = "ATH-01"
    ATH_02 = "ATH-02"
    THE_01 = "THE-01"
    PAT_01 = "PAT-01"


class SupplierCode(StrEnum):
    """The suppliers the catalogue buys from. The registry file carries the rest of their details."""

    SUP_01 = "SUP-01"
    SUP_02 = "SUP-02"
    SUP_03 = "SUP-03"
    SUP_04 = "SUP-04"


SKU_PREFIXES = {
    Category.POWER: "PWR",
    Category.DATA: "DAT",
    Category.PSU: "PSU",
    Category.UPS: "UPS",
    Category.NETWORK: "SWT",
    Category.CONNECTORS: "CON",
}

NUMERIC = "numeric"
LABEL = "label"
BOOLEAN = "boolean"

SPEC_TYPES = {
    "cores": NUMERIC,
    "section_mm": NUMERIC,
    "length_m": NUMERIC,
    "watt": NUMERIC,
    "va": NUMERIC,
    "autonomy_min": NUMERIC,
    "ports": NUMERIC,
    "speed_mbps": NUMERIC,
    "amperage": NUMERIC,
    "ip_rating": LABEL,
    "standard": LABEL,
    "shielding": LABEL,
    "efficiency": LABEL,
    "form_factor": LABEL,
    "topology": LABEL,
    "connector_type": LABEL,
    "poe": BOOLEAN,
    "managed": BOOLEAN,
}

# Labels that carry an order, weakest first.
ORDERED_LABELS = {
    "ip_rating": ["IP44", "IP54", "IP67"],
    "efficiency": ["80+ Bronze", "80+ Gold", "80+ Platinum"],
    "standard": ["CAT5e", "CAT6", "CAT6a", "CAT7"],
    "shielding": ["UTP", "FTP", "S/FTP"],
}

# Labels with no order to them, so a value is either in the list or it is wrong.
PLAIN_LABELS = {
    "form_factor": ["ATX", "SFX"],
    "topology": ["line-interactive", "online"],
    "connector_type": ["CEE", "Schuko", "IEC C13", "IEC C19"],
}

CATEGORY_SPECS = {
    Category.POWER: ["cores", "section_mm", "length_m", "watt", "ip_rating"],
    Category.DATA: ["standard", "shielding", "length_m"],
    Category.PSU: ["watt", "efficiency", "form_factor"],
    Category.UPS: ["va", "watt", "topology", "autonomy_min"],
    Category.NETWORK: ["ports", "speed_mbps", "poe", "managed"],
    Category.CONNECTORS: ["connector_type", "amperage", "ip_rating"],
}

# Lower and upper bound in euro; a product is priced somewhere inside its band.
PRICE_BANDS = {
    Category.POWER: (8.0, 180.0),
    Category.DATA: (4.5, 95.0),
    Category.PSU: (35.0, 240.0),
    Category.UPS: (95.0, 1450.0),
    Category.NETWORK: (45.0, 890.0),
    Category.CONNECTORS: (2.5, 68.0),
}


def specs_for(category: Category) -> list[str]:
    """Which specs a product of this category is expected to have."""
    return CATEGORY_SPECS[category]


def is_numeric(key: str) -> bool:
    return SPEC_TYPES.get(key) == NUMERIC


def is_flag(key: str) -> bool:
    return SPEC_TYPES.get(key) == BOOLEAN


def label_values(key: str) -> list[str]:
    """Every value a label is allowed to take."""
    return ORDERED_LABELS.get(key) or PLAIN_LABELS[key]


def ranked(key: str, value: str, op: str) -> list[str]:
    """The values of an ordered label that satisfy this comparison. IP54 or better is IP54, IP67."""
    order = ORDERED_LABELS[key]
    at = order.index(value)
    spans = {
        "eq": slice(at, at + 1),
        "gte": slice(at, None),
        "gt": slice(at + 1, None),
        "lte": slice(None, at + 1),
        "lt": slice(None, at),
    }
    return order[spans[op]]
