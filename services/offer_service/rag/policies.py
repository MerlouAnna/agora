"""
Business documents
==================
The policies and datasheets in `data/docs`, cut where they were written to be cut.

Each document was written so that a section answers on its own — no "as mentioned above",
no "see the table below" — because what a search hands back is a passage, not a document.
So the passage is the section, and it carries the document it came from and the heading it
sits under in its own text: a question about the discount policy has to be able to find it
by name.

Tables are pulled out separately and written back row by row. Read as running text, a
table comes out as `Έως 799,99 €0%` — and every threshold in these documents lives in one.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parents[3] / "data" / "docs"

SKU = re.compile(r"([A-Z]{3}-\d{4})")
EFFECTIVE = re.compile(r"Ισχύει από:\s*(.+?)(?:\s+Έκδοση|$)")
VERSION = re.compile(r"Έκδοση:\s*(\S+)")


@dataclass(frozen=True)
class Passage:
    """One section of one document, as the vector store holds it."""

    id: str
    text: str
    metadata: dict


def read_all(folder: Path | None = None) -> list[Passage]:
    """Every document in the folder, in name order.

    A file that cannot be opened is reported and skipped: one unreadable PDF is not a
    reason to leave the other nine out of the index.
    """
    folder = folder or DOCS_DIR
    passages: list[Passage] = []

    for path in sorted(folder.glob("*.pdf")):
        try:
            found = read(path)
        except Exception as exc:
            logger.warning("could not read %s — %s", path.name, exc)
            continue
        logger.info("%s — %d sections", path.name, len(found))
        passages.extend(found)

    return passages


def read(path: Path) -> list[Passage]:
    """One document, split into its sections."""
    title, effective, version, sections = _sections(path)
    sku = SKU.search(path.stem)

    passages = []
    for number, section in enumerate(sections, 1):
        body = " ".join(section["body"])
        tables = "\n".join(_written(rows) for rows in section["tables"])
        text = "\n".join(part for part in (f"{title} · {section['heading']}", body, tables) if part)

        metadata = {
            "document": path.stem,
            "title": title,
            "section": section["heading"],
            "kind": "datasheet" if sku else "policy",
            "effective": effective,
            "version": version,
        }
        if sku:
            metadata["sku"] = sku.group(1)

        passages.append(Passage(id=f"{path.stem}#{number}", text=text, metadata=metadata))

    return passages


def _sections(path: Path) -> tuple[str, str, str, list[dict]]:
    """Walk the pages, keeping headings, the text under them, and the tables between."""
    title_parts: list[str] = []
    effective = version = ""
    sections: list[dict] = []
    current: dict | None = None

    with pdfplumber.open(path) as pdf:
        body_size, title_size = _sizes(pdf)

        for page in pdf.pages:
            tables = [(table.bbox[1], table.extract()) for table in page.find_tables()]

            for top, chars in _lines(page):
                # A table sits between two headings; it belongs to the one above it.
                while tables and tables[0][0] <= top:
                    _, rows = tables.pop(0)
                    if current:
                        current["tables"].append(rows)

                size = round(max(char["size"] for char in chars), 1)
                text = "".join(char["text"] for char in chars).strip()

                if size == title_size:
                    title_parts.append(SKU.sub("", text).strip())
                elif size == body_size and current:
                    current["body"].append(text)
                elif body_size < size < title_size:
                    current = {"heading": text, "body": [], "tables": []}
                    sections.append(current)
                elif size < body_size:
                    effective = effective or _first(EFFECTIVE, text)
                    version = version or _first(VERSION, text)

            for _, rows in tables:
                if current:
                    current["tables"].append(rows)

    return " ".join(part for part in title_parts if part), effective, version, sections


def _sizes(pdf) -> tuple[float, float]:
    """The body is whatever size most of the document is set in; the title is the largest."""
    seen = Counter(round(char["size"], 1) for page in pdf.pages for char in page.chars)
    return seen.most_common(1)[0][0], max(seen)


def _lines(page) -> list[tuple[int, list]]:
    lines: dict[int, list] = {}
    for char in page.chars:
        lines.setdefault(round(char["top"]), []).append(char)
    return [(top, lines[top]) for top in sorted(lines)]


def _written(rows: list[list]) -> str:
    return "\n".join(
        " | ".join((cell or "").replace("\n", " ").strip() for cell in row) for row in rows
    )


def _first(pattern: re.Pattern, text: str) -> str:
    found = pattern.search(text)
    return found.group(1).strip() if found else ""
