"""
Graph nodes
===========
One function per step of the workflow. Each is handed the whole state and gives back only
the fields it changed, which is what LangGraph merges back in.
"""

import logging

from services.offer_service import extraction, recommendation, scenario_builder, validation
from services.offer_service.clients import catalog
from services.offer_service.graph.state import OfferState
from services.offer_service.rag import retriever

logger = logging.getLogger(__name__)


def extract(state: OfferState) -> dict:
    """The salesperson's sentence read into the requirements every later step works on."""
    read = extraction.extract(state["request"])
    return {"requirements": read.requirements, "trace": {"extract": read.trace}}


def retrieve(state: OfferState) -> dict:
    """What the builder needs out of the catalogue: the candidates and the supplier registry.

    The rows are fetched again by SKU because the index holds a card and a price, and the
    builder works on the specifications and the per-warehouse stock behind them.
    """
    found = retriever.search(state["requirements"])
    codes = [match.sku for match in found.matches]
    if not codes:
        return {"trace": {"retrieve": found.trace}}

    rows = {str(row["sku"]): row for row in catalog.lookup(codes)}
    return {
        "products": [rows[code] for code in codes if code in rows],
        "suppliers": {str(row["code"]): row for row in catalog.suppliers()},
        "trace": {"retrieve": found.trace | {"candidates": codes}},
    }


def build_scenarios(state: OfferState) -> dict:
    """The five readings of the same candidates. No model is called and nothing is fetched."""
    scenarios = scenario_builder.build(
        state["requirements"],
        state["products"],
        state["suppliers"],
        state["store"],
        state["before_cut_off"],
    )
    return {
        "scenarios": scenarios,
        "trace": {"build_scenarios": {"built": [one.lines[0].sku for one in scenarios]}},
    }


def validate(state: OfferState) -> dict:
    """Every figure each scenario claims, against the catalogue as it stands."""
    report = validation.validate(
        state["scenarios"],
        state["requirements"],
        state["store"],
        before_cut_off=state["before_cut_off"],
    )
    return {
        "report": report,
        "trace": {
            "validate": {
                "offerable": [one.lines[0].sku for one in report.offers],
                "withheld": {
                    verdict.scenario.lines[0].sku: [check.said for check in verdict.failed]
                    for verdict in report.withheld
                },
            }
        },
    }


def recommend(state: OfferState) -> dict:
    """One of the offers the check let through, named, with the words to send."""
    written = recommendation.recommend(state["report"].offers, state["requirements"])
    return {
        "recommendation": written,
        "trace": {"recommend": {"rounds": written.rounds_used, "sections": written.sections}},
    }


def no_valid_offer(state: OfferState) -> dict:
    """Why the request ends without an offer, named at the step the trail went cold."""
    said = _cold(state)
    logger.info("no offer to make — %s", said)
    return {"refused": said, "trace": {"no_valid_offer": {"because": said}}}


def route_after_validation(state: OfferState) -> str:
    """The one fork in the graph: something to recommend, or nothing."""
    return "recommend" if state["report"].offers else "no_valid_offer"


def _cold(state: OfferState) -> str:
    if not state["products"]:
        return "the catalogue holds nothing that answers the request"
    if not state["scenarios"]:
        return "nothing could be priced and dated out of what was found"

    return "every offer that was built is withheld by the check"
