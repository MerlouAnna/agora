"""
Description validator
=====================
A description is only worth keeping if the specifications the code chose can be read back
out of it. This is that check: the same parsers the ingestion uses run over the text, what
comes back is compared against what was asked for, and the answer is either nothing at all
or a sentence the model can act on.
"""

from services.data_service.categories import Category, is_numeric
from services.data_service.ingestion.parsers import extract_specs

MAX_LENGTH = 200


def check(category: Category, chosen: dict, text: str | None) -> str | None:
    """Whether a description carries the specifications it was written for.

    Args:
        category: Decides which specs the parsers look for.
        chosen: What the code picked, keyed as the registry names it.
        text: The description under test.

    Returns:
        None when the text is usable, otherwise what is wrong with it, in words.
    """
    if text is None or not text.strip():
        return "nothing was returned for this product"

    if len(text) > MAX_LENGTH:
        return f"too long at {len(text)} characters — keep it under {MAX_LENGTH}"

    found = extract_specs(category, text)

    missing = [key for key in chosen if key not in found]
    if missing:
        return "these cannot be read out of the text: " + ", ".join(
            f"{key} ({chosen[key]})" for key in missing
        )

    wrong = [
        f"{key} reads as {found[key]} but should be {chosen[key]}"
        for key in chosen
        if not _matches(key, found[key], chosen[key])
    ]
    if wrong:
        return "; ".join(wrong)

    return None


def _matches(key: str, found, chosen) -> bool:
    if isinstance(chosen, bool):
        return bool(found) is chosen
    if is_numeric(key):
        return abs(float(found) - float(chosen)) < 1e-6
    return str(found) == str(chosen)
