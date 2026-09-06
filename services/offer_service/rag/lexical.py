"""
Lexical search
==============
BM25 over the same cards the vectors were made from, for the tokens a vector blurs: a
pasted code, a section, a standard written the way it is printed on the box.
"""

import re

from rank_bm25 import BM25Okapi

# Keep `3x2.5mm`, `s/ftp`, `cat6a` and `80+` in one piece: they are the tokens that matter.
WORD = re.compile(r"[\w./+]+")


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


def ranked(query: str, codes: list[str], texts: list[str]) -> list[str]:
    """The codes, best match first. Ties break on the code, so two runs agree."""
    if not codes:
        return []

    scores = BM25Okapi([words(text) for text in texts]).get_scores(words(query))
    ordered = sorted(zip(codes, scores, strict=True), key=lambda pair: (-pair[1], pair[0]))
    return [code for code, _ in ordered]
