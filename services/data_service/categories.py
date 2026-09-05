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
    "poe": LABEL,
    "managed": LABEL,
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
