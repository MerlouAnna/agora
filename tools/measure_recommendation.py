"""
Recommendation measurement
==========================
Four questions about the last node, none of them "was the recommendation good" — there is
no query that answers that, and a score for it would be the model marking its own work.
What can be asked: how often the answer had to be sent back before it stayed inside the
offers, whether it says the things the offers oblige it to say, whether it picked an offer
another one beats on every axis, and whether the same request answers the same way twice.

Builds and validates each request of the scenario eval first, so the offers it recommends
over are the ones tools/measure_scenarios.py has already held against the catalogue.

Reads data/docs and data/catalog.db, and calls the model once per request per round.

Run from the repository root:  python -m tools.measure_recommendation [runs]
"""

import json
import logging
import sys
from pathlib import Path

from services.data_service.delivery import Store
from services.offer_service import recommendation, validation
from services.offer_service import scenario_builder as builder
from services.offer_service.domain.models import Availability, OfferScenario
from services.offer_service.requirements import CustomerRequirements
from tools.measure_scenarios import catalogue

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EVAL_FILE = Path(__file__).resolve().parent.parent / "tests" / "data" / "scenario_eval.json"
MISSED = "does not meet"


def obliged(one: OfferScenario) -> list[tuple[str, tuple[str, ...]]]:
    """What the recommendation has to mention, given the offer it recommends.

    Each entry is what the condition is called and the words that would count as saying it.
    Written by hand from the four things a customer would otherwise discover later.
    """
    owed = []
    if one.needs_approval:
        owed.append(("the approval", ("έγκρι", "προϊστάμ", "προϊστα")))
    if one.availability == Availability.ORDERED:
        owed.append(("the quantity being ordered in", ("παραγγελ", "απόθεμα", "αποθέματ")))
    if one.availability == Availability.UNKNOWN:
        owed.append(("the stock nobody can confirm", ("απόθεμα", "αποθέματ", "επιβεβαι")))
    if any(MISSED in note for note in one.notes):
        owed.append(("the condition it misses", ("δεν", "χωρίς", "μόνο")))

    return owed


def beaten(picked: OfferScenario, offers: list[OfferScenario]) -> str | None:
    """Whether another offer is at least as good on every axis and better on one."""
    for other in offers:
        if other is picked or other.days is None or picked.days is None:
            continue
        atleast = other.total <= picked.total and other.days <= picked.days
        better = other.total < picked.total or other.days < picked.days
        misses = any(MISSED in note for note in other.notes)
        if atleast and better and not misses:
            return other.lines[0].sku

    return None


def measured(case: dict, rows: dict, suppliers: dict) -> dict:
    """One request, from its candidates to the sentence a salesperson would send."""
    asked = CustomerRequirements(request=case["request"], **case["requirements"])
    store = Store(case["store"])
    built = builder.build(asked, [rows[sku] for sku in case["candidates"]], suppliers, store)
    report = validation.validate(
        built,
        asked,
        store,
        catalogue=lambda skus: [rows[sku] for sku in skus if sku in rows],
        registry=lambda: list(suppliers.values()),
    )
    offers = report.offers
    row = {"id": case["id"], "offered": len(offers)}

    try:
        written = recommendation.recommend(offers, asked)
    except recommendation.RecommendationFailed as exc:
        return row | {"sku": "—", "rounds": recommendation.MAX_ROUNDS, "said": [str(exc)[:160]]}

    picked = next(one for one in offers if one.lines[0].sku == written.sku)
    said = " ".join([written.text, *written.watch_out]).lower()
    missing = [name for name, words in obliged(picked) if not any(word in said for word in words)]
    beat = beaten(picked, offers)

    return row | {
        "sku": written.sku,
        "rounds": written.rounds_used,
        "sections": len(written.sections),
        "said": [f"never says {name}" for name in missing]
        + ([f"{beat} beats it on every axis"] if beat else []),
        "text": written.text,
    }


def table(rows: list[dict]) -> int:
    logger.info("")
    logger.info("%-28s %-9s %-7s %-9s %s", "request", "picked", "rounds", "sections", "findings")
    wrong = 0
    for row in rows:
        wrong += len(row["said"])
        logger.info(
            "%-28s %-9s %-7s %-9s %s",
            row["id"],
            row["sku"],
            row["rounds"],
            row.get("sections", "—"),
            "—" if not row["said"] else "; ".join(row["said"]),
        )

    logger.info("")
    logger.info(
        "   %d of %d answered first time, %d findings",
        sum(1 for row in rows if row["rounds"] == 1),
        len(rows),
        wrong,
    )
    return wrong


def run(runs: int = 1) -> None:
    cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))["cases"]
    rows, suppliers = catalogue()

    logger.info("%d requests, %d run(s), one model call per request per round", len(cases), runs)

    wrong = 0
    seen: dict[str, list[str]] = {case["id"]: [] for case in cases}
    for attempt in range(1, runs + 1):
        answered = [measured(case, rows, suppliers) for case in cases]
        logger.info("")
        logger.info("run %d of %d", attempt, runs)
        wrong += table(answered)
        for row in answered:
            seen[row["id"]].append(row["sku"])

    if runs > 1:
        logger.info("")
        logger.info("the same request, run again")
        unsteady = {name: set(picks) for name, picks in seen.items() if len(set(picks)) > 1}
        for name, picks in unsteady.items():
            logger.info("   ✘ %-28s picked %s", name, ", ".join(sorted(picks)))
        logger.info(
            "   %d of %d picked the same offer every time", len(seen) - len(unsteady), len(seen)
        )
        wrong += len(unsteady)

    logger.info("")
    logger.info("%s", "nothing to answer for" if not wrong else f"{wrong} to answer for")
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
