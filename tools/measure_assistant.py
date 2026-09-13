"""
Assistant measurement
=====================
Five questions about the question path, none of them "was the answer good" — there is no
query that answers that. What can be asked: did the model call the tool the question needs
with the arguments that matter, does the answer carry the facts the catalogue and the
documents hold, does it cite a code that is grounded but beside the point, how often was it
sent back, and does the same question answer the same way twice. The facts were written by
hand from the database and the documents, never from a run.

Needs the data service up and a key in the environment. The graph runs here, handed the
history a follow-up would have been handed, so the offer service is not called and nothing
is written into the conversations.

Run from the repository root:  python -m tools.measure_assistant [runs]
"""

import json
import logging
import sys
from pathlib import Path

from services.offer_service.assistant import graph as assistant
from services.offer_service.clients import catalog

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

EVAL_FILE = Path(__file__).resolve().parent.parent / "tests" / "data" / "assistant_eval.json"


def measured(case: dict, graph, matters: dict[str, set[str]]) -> dict:
    """One case, turn by turn, each later turn shown the ones before it as the router would.

    `matters` names, per tool, the arguments the eval cares about anywhere; the free text a
    search is asked with is reworded every run and is not one of them.
    """
    history: list[dict] = []
    called: list[list[str]] = []
    repairs = 0
    state = None
    for turn in case["turns"]:
        state = graph.invoke(assistant.make_initial_state(turn, history))
        called.append(state["tools_used"])
        repairs += state["repairs"]
        answer = state["answer"] if state["refused"] is None else state["refused"]
        history += [{"role": "user", "content": turn}, {"role": "assistant", "content": answer}]

    answer = history[-1]["content"]
    cited = [code for code in case.get("must_not", []) if code in answer]
    said = [
        f"never called {spelled(call)}"
        for expected, used in zip(case["tools"], called, strict=True)
        for call in expected
        if not any(matches(call, one) for one in used)
    ]
    said += [
        f"never says {spellings[0]}"
        for spellings in case["facts"]
        if not any(spelling.casefold() in answer.casefold() for spelling in spellings)
    ]
    said += [f"cites {code}" for code in cited]
    if state["refused"] is not None:
        said.append("refused")

    return {
        "id": case["id"],
        "tools": " · ".join(
            ", ".join(spelled(one, matters) for one in used) or "—" for used in called
        ),
        "cited": ", ".join(cited) or "—",
        "repairs": repairs,
        "refused": state["refused"] is not None,
        "said": said,
        "answer": answer,
    }


def matches(expected: dict, call: dict) -> bool:
    """The same tool, and every argument the eval names with the value it names."""
    if call["name"] != expected["name"]:
        return False

    given = call.get("arguments") or {}
    return all(given.get(key) == value for key, value in expected.get("arguments", {}).items())


def spelled(call: dict, matters: dict[str, set[str]] | None = None) -> str:
    """A call as one token, with the arguments that matter and no others."""
    arguments = call.get("arguments") or {}
    keys = arguments if matters is None else matters.get(call["name"], set())
    inside = ", ".join(f"{key}={arguments[key]}" for key in arguments if key in keys)
    return f"{call['name']}({inside})"


def argued(cases: list[dict]) -> dict[str, set[str]]:
    """Per tool, every argument the eval names for it."""
    matters: dict[str, set[str]] = {}
    for case in cases:
        for turn in case["tools"]:
            for call in turn:
                matters.setdefault(call["name"], set()).update(call.get("arguments", {}))

    return matters


def table(rows: list[dict]) -> int:
    logger.info("")
    logger.info(
        "%-24s %-58s %-9s %-8s %-8s %s",
        "case",
        "tools called",
        "must_not",
        "repairs",
        "refused",
        "findings",
    )
    wrong = 0
    for row in rows:
        wrong += len(row["said"])
        logger.info(
            "%-24s %-58s %-9s %-8d %-8s %s",
            row["id"],
            row["tools"],
            row["cited"],
            row["repairs"],
            "yes" if row["refused"] else "—",
            "—" if not row["said"] else "; ".join(row["said"]),
        )

    logger.info("")
    logger.info(
        "   %d of %d clean, %d findings",
        sum(1 for row in rows if not row["said"]),
        len(rows),
        wrong,
    )
    return wrong


def wrote(rows: list[dict]) -> None:
    """The answers themselves, which no column above is a substitute for."""
    logger.info("")
    logger.info("what it wrote")
    for row in rows:
        logger.info("")
        logger.info("%s", row["id"])
        logger.info("   %s", row["answer"].replace("\n", " "))


def run(runs: int = 1) -> None:
    cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))["cases"]
    try:
        catalog.stats()
    except catalog.CatalogueUnavailable as exc:
        logger.error("the data service is not answering — %s", exc)
        sys.exit(1)

    graph = assistant.build_graph()
    matters = argued(cases)
    turns = sum(len(case["turns"]) for case in cases)
    logger.info(
        "%d cases, %d turns, %d run(s) — at least one model call per turn", len(cases), turns, runs
    )

    wrong = 0
    seen: dict[str, list[str]] = {case["id"]: [] for case in cases}
    for attempt in range(1, runs + 1):
        answered = [measured(case, graph, matters) for case in cases]
        logger.info("")
        logger.info("run %d of %d", attempt, runs)
        wrong += table(answered)
        wrote(answered)
        for row in answered:
            seen[row["id"]].append(
                f"{row['tools']} / {'refused' if row['refused'] else 'answered'}"
            )

    if runs > 1:
        logger.info("")
        logger.info("the same question, run again")
        unsteady = {name: set(ways) for name, ways in seen.items() if len(set(ways)) > 1}
        for name, ways in unsteady.items():
            logger.info("   ✘ %-24s %s", name, " | ".join(sorted(ways)))
        logger.info(
            "   %d of %d called the same tools and ended the same way every time",
            len(seen) - len(unsteady),
            len(seen),
        )
        wrong += len(unsteady)

    logger.info("")
    logger.info("%s", "nothing to answer for" if not wrong else f"{wrong} to answer for")
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
