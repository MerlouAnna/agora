"""
Parsers
=======
Turning the strings the source systems produce into typed values. Every regex in the
ingestion package lives here, and nothing in this module touches a file or the database.

A parser returns the value it managed to read, or None when the text does not hold one.
Whether a value that parsed is acceptable — a price above zero, a quantity that covers an
order — is a business rule and belongs with the canonical record, not here.
"""

import re
from datetime import date, datetime, timedelta

from services.data_service.categories import Category, specs_for

DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%m/%d/%Y")
# Excel counts days from here, including the 1900 leap year that never happened.
EXCEL_EPOCH = date(1899, 12, 30)
EXCEL_SERIAL = re.compile(r"^\d{5}$")
# Five digits that land outside these are a truncated number, not a date.
SERIAL_EARLIEST = date(1990, 1, 1)
SERIAL_LATEST = date(2100, 1, 1)

SKU_PATTERN = re.compile(r"^([A-Z]{3})(\d{4})$")
SKU_NOISE = re.compile(r"[^A-Za-z0-9]")
PRICE_CLEAN = re.compile(r"[^\d,.\-]")
LENGTH_PATTERN = re.compile(r"(\d+)\s*(cm|μ\.|m)(?!m)")
WATT_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kW|W)\b")

CORES_PATTERN = re.compile(r"(\d+)x[\d.]+mm")
SECTION_PATTERN = re.compile(r"\d+x([\d.]+)mm")
IP_PATTERN = re.compile(r"\b(IP\d{2})\b")
VA_PATTERN = re.compile(r"(\d+)\s*VA\b")
AUTONOMY_PATTERN = re.compile(r"αυτονομία\s+(\d+)\s+λεπτά")
PORTS_PATTERN = re.compile(r"(\d+)\s+θυρών")
SPEED_PATTERN = re.compile(r"(\d+)\s*Mbps\b")
AMPERAGE_PATTERN = re.compile(r"(\d+)\s*A\b")
STANDARD_PATTERN = re.compile(r"\b(CAT\d+[a-zA-Z]?)\b")
SHIELDING_PATTERN = re.compile(r"\b(S/FTP|FTP|UTP)\b")
EFFICIENCY_PATTERN = re.compile(r"(80\+\s+\w+)")
FORM_FACTOR_PATTERN = re.compile(r"\b(ATX|SFX)\b")
TOPOLOGY_PATTERN = re.compile(r"\b(line-interactive|online)\b")
CONNECTOR_PATTERN = re.compile(r"\b(IEC C13|IEC C19|Schuko|CEE)\b")


# ── Fields ───────────────────────────────────────────────────────────────────


def normalize_sku(raw: str) -> str | None:
    """Reduce any spelling of a SKU to `PWR-1007`.

    Everything that is not a letter or a digit comes out first, which covers the dashes
    and spaces the three source systems disagree on, and the quotes people paste around
    a code when they copy it from somewhere else.
    """
    if not raw:
        return None

    compact = SKU_NOISE.sub("", raw).upper()
    match = SKU_PATTERN.match(compact)
    if match is None:
        return None

    return f"{match.group(1)}-{match.group(2)}"


def parse_price(raw: str) -> float | None:
    """Read a price written with a euro sign, a comma decimal, a trailing EUR, or none."""
    if not raw:
        return None

    cleaned = PRICE_CLEAN.sub("", raw)
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")

    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_quantity(raw: str) -> int | None:
    if not raw:
        return None

    try:
        return int(raw.strip())
    except ValueError:
        return None


def parse_date(raw: str) -> date | None:
    """A date however the file wrote it, spreadsheet serial numbers included.

    A column somebody opened in Excel comes back as 46266 rather than 2026-09-01, because
    the cell was a date and the format was General. That is not a corrupt file, it is a
    spreadsheet, and it is the most common thing to arrive in one.
    """
    if not raw:
        return None

    text = raw.strip()

    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue

    if EXCEL_SERIAL.match(text):
        moment = EXCEL_EPOCH + timedelta(days=int(text))
        if SERIAL_EARLIEST <= moment <= SERIAL_LATEST:
            return moment

    return None


def parse_length_m(text: str) -> int | None:
    """Metres, whether the source wrote 20m, 20 μ. or 2000cm."""
    match = LENGTH_PATTERN.search(text)
    if match is None:
        return None

    value, unit = int(match.group(1)), match.group(2)
    return value // 100 if unit == "cm" else value


def parse_watt(text: str) -> int | None:
    match = WATT_PATTERN.search(text)
    if match is None:
        return None

    value = float(match.group(1).replace(",", "."))
    if match.group(2) == "kW":
        value *= 1000

    return int(value)


# ── Specs ────────────────────────────────────────────────────────────────────

_SIMPLE_SPECS = {
    "cores": (CORES_PATTERN, int),
    "section_mm": (SECTION_PATTERN, float),
    "ip_rating": (IP_PATTERN, str),
    "va": (VA_PATTERN, int),
    "autonomy_min": (AUTONOMY_PATTERN, int),
    "ports": (PORTS_PATTERN, int),
    "speed_mbps": (SPEED_PATTERN, int),
    "amperage": (AMPERAGE_PATTERN, int),
    "standard": (STANDARD_PATTERN, str),
    "shielding": (SHIELDING_PATTERN, str),
    "efficiency": (EFFICIENCY_PATTERN, str),
    "form_factor": (FORM_FACTOR_PATTERN, str),
    "topology": (TOPOLOGY_PATTERN, str),
    "connector_type": (CONNECTOR_PATTERN, str),
}


def extract_specs(category: Category, description: str) -> dict:
    """Pull the specs the category declares out of the description text.

    Args:
        category: Decides which specs are looked for at all.
        description: The Greek text as the ERP holds it.

    Returns:
        The specs that were found, keyed as the registry names them. A spec the text
        does not mention is simply absent, so the caller can tell it apart from one
        that was read as zero.
    """
    found = {}

    for key in specs_for(category):
        if key == "length_m":
            value = parse_length_m(description)
        elif key == "watt":
            value = parse_watt(description)
        elif key == "poe":
            value = "poe" in description.lower()
        elif key == "managed":
            # "managed" sits inside "unmanaged", so the negative has to be ruled out first.
            lowered = description.lower()
            value = "unmanaged" not in lowered and "managed" in lowered
        else:
            pattern, convert = _SIMPLE_SPECS[key]
            match = pattern.search(description)
            value = convert(match.group(1)) if match else None

        if value is not None:
            found[key] = value

    return found
