"""
Policy retrieval measurement
============================
Runs the questions in tests/data/policy_eval.json against the business documents and says
how many of the sections that answer each one came back, at two cut-offs.

The product eval's answers are computed with SQL. These are not: which section answers a
question is a reading, not a query, so this is the weaker of the two measurements and the
number should be read as such.

Run from the repository root:  python -m tools.measure_policies
"""

import json
import logging
from pathlib import Path

from services.offer_service.rag import embeddings, lexical, policies, retriever
from tools.measure_retrieval import CUTOFFS, recall

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EVAL_FILE = Path(__file__).resolve().parent.parent / "tests" / "data" / "policy_eval.json"
COLUMNS = ("words", "meaning", "merged")
KEYS = ("by_word", "by_meaning", "merged")


def corpus() -> tuple[list[str], list[str]]:
    """The documents as the index holds them, read by the code that fills the index."""
    passages = policies.read_all()
    return [passage.id for passage in passages], [passage.text for passage in passages]


def reachable() -> bool:
    """Whether the meaning side can be measured at all, asked once rather than per question."""
    try:
        retriever.search_policies("δοκιμή", limit=1)
    except (retriever.IndexNotBuilt, embeddings.EmbeddingsUnavailable) as exc:
        logger.info("only the words can be measured — %s", exc)
        return False

    return True


def rankings(question: str, corpus_: tuple, whole: bool) -> dict:
    """One ordering per column for one question."""
    if not whole:
        return {"words": lexical.ranked(question, *corpus_)}

    _, trace = retriever.search_policies(question, limit=max(CUTOFFS))
    return {name: trace[key] for name, key in zip(COLUMNS, KEYS, strict=True)}


def run() -> None:
    cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))["cases"]
    corpus_ = corpus()
    whole = reachable()
    columns = COLUMNS if whole else COLUMNS[:1]
    totals = {(name, at): 0.0 for name in columns for at in CUTOFFS}

    logger.info("%d sections, %d questions", len(corpus_[0]), len(cases))
    logger.info("")
    logger.info("%-24s" + " %-12s" * len(columns), "question", *columns)
    logger.info("%-24s" + " %-12s" * len(columns), "", *["@5   @10"] * len(columns))

    for case in cases:
        found = rankings(case["question"], corpus_, whole)
        scored = {
            (name, at): recall(found[name], case["expected"], at)
            for name in columns
            for at in CUTOFFS
        }
        for key, value in scored.items():
            totals[key] += value

        logger.info(
            "%-24s" + " %-12s" * len(columns),
            case["id"],
            *[_pair(scored, name) for name in columns],
        )

    means = {key: value / len(cases) for key, value in totals.items()}
    logger.info("")
    logger.info(
        "%-24s" + " %-12s" * len(columns), "MEAN", *[_pair(means, name) for name in columns]
    )


def _pair(scored: dict, name: str) -> str:
    return " ".join(f"{scored[(name, at)]:<4.0%}" for at in CUTOFFS)


if __name__ == "__main__":
    run()
