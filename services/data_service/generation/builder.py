"""
Record builder
==============
What a product of a given category actually is: the specs it carries, the price it sits
at, and the Greek text an ERP would hold for it. The registry says which specs a
category declares; this module picks the values from a seeded generator, so the same
seed always gives back the same products.

The three source systems never wrote a length or a wattage the same way, and the text
built here reproduces that spread on purpose — the parsers have to survive all of it.
"""

import random

from services.data_service.categories import ORDERED_LABELS, PLAIN_LABELS, PRICE_BANDS, Category

DEFAULT_BRANDS = ["Elektra", "Voltera", "Nordion", "Kyma", "Delta Line"]

# Numbers a warehouse actually reports. Zero appears twice because roughly a quarter of
# the catalogue is out of stock at any given moment.
QUANTITIES = [0, 0, 4, 12, 25, 40, 80, 150]

SKU_START = 1000
SKU_LIMIT = 9999


def build_specs(category: Category, rng: random.Random) -> dict:
    """Plausible technical specs for one product of this category.

    Args:
        category: Decides which specs are drawn at all.
        rng: Seeded generator.

    Returns:
        Every spec the registry declares for the category, with a value.
    """
    if category == Category.POWER:
        return {
            "cores": rng.choice([3, 5]),
            "section_mm": rng.choice([1.5, 2.5, 4.0, 6.0]),
            "length_m": rng.choice([5, 10, 15, 20, 25, 30, 50]),
            "watt": rng.choice([750, 1000, 1500, 2200, 3000]),
            "ip_rating": rng.choice(ORDERED_LABELS["ip_rating"]),
        }
    if category == Category.DATA:
        return {
            "standard": rng.choice(ORDERED_LABELS["standard"]),
            "shielding": rng.choice(ORDERED_LABELS["shielding"]),
            "length_m": rng.choice([1, 3, 5, 10, 15, 20, 30]),
        }
    if category == Category.PSU:
        return {
            "watt": rng.choice([450, 550, 650, 750, 850, 1000]),
            "efficiency": rng.choice(ORDERED_LABELS["efficiency"]),
            "form_factor": rng.choice(PLAIN_LABELS["form_factor"]),
        }
    if category == Category.UPS:
        va = rng.choice([650, 1000, 1500, 2200, 3000])
        return {
            "va": va,
            "watt": int(va * 0.6),
            "topology": rng.choice(PLAIN_LABELS["topology"]),
            "autonomy_min": rng.choice([8, 12, 20, 35]),
        }
    if category == Category.NETWORK:
        return {
            "ports": rng.choice([8, 16, 24, 48]),
            "speed_mbps": rng.choice([100, 1000, 2500]),
            "poe": rng.choice([True, False]),
            "managed": rng.choice([True, False]),
        }
    return {
        "connector_type": rng.choice(PLAIN_LABELS["connector_type"]),
        "amperage": rng.choice([16, 32, 63]),
        # Two of the three on purpose: the middle rating never appears on a connector.
        "ip_rating": rng.choice(["IP44", "IP67"]),
    }


def length_text(metres: int, rng: random.Random) -> str:
    """Three ways of writing the same length, because three systems typed it."""
    return rng.choice([f"{metres}m", f"{metres} μ.", f"{metres * 100}cm"])


def watt_text(watt: int, rng: random.Random) -> str:
    if watt >= 1000 and watt % 1000 == 0 and rng.random() < 0.4:
        return f"{watt // 1000}kW"
    return f"{watt}W"


def describe(category: Category, specs: dict, rng: random.Random) -> str:
    """The Greek description as the ERP holds it, with the specs inside the text."""
    if category == Category.POWER:
        return "Καλώδιο ρεύματος {}x{}mm {} {} {} εξωτερικού χώρου".format(
            specs["cores"],
            specs["section_mm"],
            length_text(specs["length_m"], rng),
            watt_text(specs["watt"], rng),
            specs["ip_rating"],
        )
    if category == Category.DATA:
        return "Καλώδιο δικτύου {} {} {}".format(
            specs["standard"], specs["shielding"], length_text(specs["length_m"], rng)
        )
    if category == Category.PSU:
        return "Τροφοδοτικό {} {} {}".format(
            watt_text(specs["watt"], rng), specs["efficiency"], specs["form_factor"]
        )
    if category == Category.UPS:
        return "UPS {} {}VA / {} αυτονομία {} λεπτά".format(
            specs["topology"],
            specs["va"],
            watt_text(specs["watt"], rng),
            specs["autonomy_min"],
        )
    if category == Category.NETWORK:
        extras = " PoE" if specs["poe"] else ""
        extras += " managed" if specs["managed"] else " unmanaged"
        return "Switch {} θυρών {}Mbps{}".format(
            specs["ports"], specs["speed_mbps"], extras
        )
    return "Ρευματολήπτης {} {}A {}".format(
        specs["connector_type"], specs["amperage"], specs["ip_rating"]
    )


def price_for(
    category: Category, rng: random.Random, band: tuple[float, float] | None = None
) -> float:
    """A price inside the category's band, unless the caller supplied its own."""
    low, high = band if band is not None else PRICE_BANDS[category]
    return round(rng.uniform(low, high), 2)
