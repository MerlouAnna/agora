"""
Grounding
=========
Whether an answer stays inside what the tools returned this turn. Every figure in it has
to be findable there or in the question; a product code may also come from an earlier turn
of the conversation, since that is the subject being talked about. Numbering that opens a
line of a list is typography, not a figure. Whatever is not is handed back as the model
wrote it.
"""

import re

SKU = re.compile(r"\b[A-Z]{3}-\d{4}\b")
NUMBER = re.compile(r"\d[\d.,]*")
GROUPED = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?")
LIST_MARKER = re.compile(r"^[ \t]*\d+[.)][ \t]+", re.MULTILINE)


def unsupported(
    answer: str, evidence: list[str], question: str, earlier: list[str] | None = None
) -> list[str]:
    """What in the answer no tool returned, in the order and the spelling it was written.

    Args:
        answer: What the model wrote.
        evidence: The tool results of this turn, as the model saw them.
        question: The salesperson's words, whose own codes and figures may be repeated.
        earlier: The turns the model was shown as context. Their codes may be named again;
            their figures may not.

    Returns:
        The codes and figures found nowhere they are allowed. Empty when the answer holds.
    """
    given = " ".join([question, *evidence])
    codes = set(SKU.findall(" ".join([given, *(earlier or [])])))
    allowed = {
        _plain(figure) for raw in NUMBER.findall(given) for figure in _readings(raw.strip(".,"))
    }

    strange: list[str] = []
    for code in SKU.findall(answer):
        if code not in codes and code not in strange:
            strange.append(code)

    for raw in NUMBER.findall(LIST_MARKER.sub("", SKU.sub("", answer))):
        figure = _read(raw.strip(".,"))
        if figure is not None and _plain(figure) not in allowed and raw not in strange:
            strange.append(raw)

    return strange


def _readings(raw: str) -> list[float]:
    """Both things a token in the evidence could mean: JSON writes 61.57, a document 1.500,00."""
    found = []
    for figure in (_read(raw), _float(raw)):
        if figure is not None and figure not in found:
            found.append(figure)

    return found


def _read(raw: str) -> float | None:
    """A figure the way Greek writes it: the dot groups thousands, the comma is the decimal."""
    if GROUPED.fullmatch(raw):
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(",") == 1 and "." not in raw:
        raw = raw.replace(",", ".")
    elif "," in raw or raw.count(".") > 1:
        return None

    return _float(raw)


def _float(raw: str) -> float | None:
    try:
        return float(raw)
    except ValueError:
        return None


def _plain(figure: float) -> str:
    return str(int(figure)) if figure.is_integer() else f"{figure:.2f}"
