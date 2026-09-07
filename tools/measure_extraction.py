"""
Extraction measurement
======================
Runs the requests in tests/data/retrieval_eval.json through the extractor and compares
what came out with the requirements the file already carries — the ones a perfect
extractor would produce, written by hand before the extractor existed.

Three things are measured: how often the extraction is exact, what the difference costs
in recall when it is not, and whether the same request gets the same answer twice.

Unlike the other two tools this one calls the model, once per request per round.

Run from the repository root:  python -m tools.measure_extraction [runs]
"""

import json
import logging
import sys

from services.offer_service import extraction
from services.offer_service.rag import embeddings, retriever
from services.offer_service.requirements import CustomerRequirements
from tools.measure_retrieval import CUTOFFS, EVAL_FILE, affordable, current, recall, scorable

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

FIELDS = ("category", "quantity", "price_min", "price_max", "immediate")


def measured(case: dict, held: tuple, by_hand: dict) -> dict:
    """One request: what the extractor made of it, and what that cost."""
    wanted = CustomerRequirements(request=case["request"], **case["requirements"])
    row = {"id": case["id"], "by_hand": by_hand[case["id"]]}

    try:
        found = extraction.extract(case["request"])
    except extraction.ExtractionFailed as exc:
        return row | {
            "differs": [f"handed back after {extraction.MAX_ROUNDS} rounds — {exc}"],
            "rounds": extraction.MAX_ROUNDS,
        }

    got = found.requirements
    return row | {
        "differs": differences(got, wanted),
        "rounds": found.trace["rounds"],
        "extracted": scored(got, case, held),
        "fingerprint": fingerprint(got),
    }


def scored(requirements: CustomerRequirements, case: dict, held: tuple) -> dict:
    """What these requirements find, at both cut-offs."""
    scorable(requirements)
    codes, _ = retriever.candidates(requirements, limit=retriever.CANDIDATES)
    reached = affordable(codes, requirements, held)

    return {at: recall(reached, case["expected"], at) for at in CUTOFFS}


def differences(got: CustomerRequirements, wanted: CustomerRequirements) -> list[str]:
    """Every way the extraction departs from the hand-written answer, named one by one."""
    said = [
        f"{field} {getattr(got, field)!r} not {getattr(wanted, field)!r}"
        for field in FIELDS
        if getattr(got, field) != getattr(wanted, field)
    ]
    if ordering(got) != ordering(wanted):
        said.append(f"order {ordering(got)} not {ordering(wanted)}")

    mine, theirs = constraints(got), constraints(wanted)
    said += [f"invented {one}" for one in sorted(mine - theirs)]
    said += [f"missed {one}" for one in sorted(theirs - mine)]

    return said


def constraints(requirements: CustomerRequirements) -> set[str]:
    return {f"{c.key} {c.op} {plain(c.value)}" for c in requirements.constraints}


def ordering(requirements: CustomerRequirements) -> str:
    order = requirements.order
    return f"{order.key} {order.end}" if order is not None else "none"


def fingerprint(requirements: CustomerRequirements) -> str:
    """The whole extraction as one string, so two runs can be compared for equality."""
    fields = [f"{field}={getattr(requirements, field)}" for field in FIELDS]

    return " | ".join([*fields, ordering(requirements), *sorted(constraints(requirements))])


def plain(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value)


def table(rows: list[dict]) -> None:
    logger.info("")
    logger.info("%-28s %-6s %-7s %-12s %-12s", "request", "exact", "rounds", "by hand", "extracted")
    logger.info("%-28s %-6s %-7s %-12s %-12s", "", "", "", "@5   @10", "@5   @10")

    exact = 0
    totals = {("by_hand", at): 0.0 for at in CUTOFFS} | {("extracted", at): 0.0 for at in CUTOFFS}
    for row in rows:
        exact += not row["differs"]
        for which in ("by_hand", "extracted"):
            for at in CUTOFFS:
                totals[(which, at)] += row.get(which, {}).get(at, 0.0)

        logger.info(
            "%-28s %-6s %-7s %-12s %-12s",
            row["id"],
            "✔" if not row["differs"] else "✘",
            row["rounds"],
            pair(row.get("by_hand")),
            pair(row.get("extracted")),
        )

    means = {key: value / len(rows) for key, value in totals.items()}
    logger.info(
        "%-28s %-6s %-7s %-12s %-12s",
        "MEAN",
        f"{exact}/{len(rows)}",
        "",
        pair({at: means[("by_hand", at)] for at in CUTOFFS}),
        pair({at: means[("extracted", at)] for at in CUTOFFS}),
    )

    told = [row for row in rows if row["differs"]]
    if told:
        logger.info("")
        logger.info("what differed")
        for row in told:
            for said in row["differs"]:
                logger.info("   %-28s %s", row["id"], said)


def stability(seen: dict[str, list[str]]) -> None:
    """A request that answers differently on two identical runs is not a measurement yet."""
    logger.info("")
    logger.info("the same request, run again")
    asked = {name: answers for name, answers in seen.items() if answers}
    steady = 0
    for name, answers in asked.items():
        distinct = len(set(answers))
        steady += distinct == 1
        if distinct > 1:
            logger.info("   %-28s %d different answers in %d runs", name, distinct, len(answers))

    logger.info("   %d of %d requests answered the same way every time", steady, len(asked))
    if len(asked) < len(seen):
        logger.info("   %d were never asked — the run stopped early", len(seen) - len(asked))


def run(runs: int = 1) -> None:
    cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))["cases"]
    held = current()

    try:
        retriever.candidates(CustomerRequirements(request="καλώδιο"), limit=1)
    except (retriever.IndexNotBuilt, embeddings.EmbeddingsUnavailable) as exc:
        sys.exit(f"the extraction cannot be measured against an index that is not there — {exc}")

    logger.info("%d requests, %d run(s), one model call per request per round", len(cases), runs)
    by_hand = {
        case["id"]: scored(
            CustomerRequirements(request=case["request"], **case["requirements"]), case, held
        )
        for case in cases
    }

    seen: dict[str, list[str]] = {case["id"]: [] for case in cases}
    for attempt in range(1, runs + 1):
        rows = []
        for case in cases:
            try:
                rows.append(measured(case, held, by_hand))
            except extraction.ModelUnavailable as exc:
                logger.error(
                    "the model stopped answering after %d of %d requests — %s",
                    len(rows),
                    len(cases),
                    exc,
                )
                break

        logger.info("")
        logger.info("run %d of %d", attempt, runs)
        if rows:
            table(rows)
        for row in rows:
            seen[row["id"]].append(row.get("fingerprint", "handed back"))
        if len(rows) < len(cases):
            break

    if runs > 1:
        stability(seen)


def pair(scores: dict | None) -> str:
    if not scores:
        return "—"

    return " ".join(f"{scores[at]:<4.0%}" for at in CUTOFFS)


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
