"""
One request, end to end
=======================
Runs the graph over a request written on the command line and prints what each step made
of it: the requirements, the candidates, the offers, what the check withheld, and the
answer the salesperson would send.

Needs both services indexed and the data service running, and calls the model twice.

Run from the repository root:  python -m tools.run_offer "<request>" [store]
"""

import logging
import sys

from services.data_service.delivery import Store
from services.offer_service import extraction, recommendation
from services.offer_service import scenario_builder as builder
from services.offer_service.clients import catalog
from services.offer_service.graph.builder import build_graph
from services.offer_service.graph.state import make_initial_state
from services.offer_service.rag import embeddings, retriever

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("run_offer")

# What the salesperson decides on, which is why the approval has a column of its own.
COLUMNS = "%-9s %-33s %-10s %-6s %-9s %-7s %s"

# Every way the run can stop that is the environment or the model, not a defect.
STOPPED = (
    catalog.CatalogueUnavailable,
    embeddings.EmbeddingsUnavailable,
    extraction.ExtractionFailed,
    extraction.ModelUnavailable,
    recommendation.ModelUnavailable,
    recommendation.RecommendationFailed,
    retriever.IndexNotBuilt,
)


def show(state: dict) -> None:
    """What the graph made of the request, step by step."""
    asked = state["requirements"]
    found = state["trace"]["retrieve"].get("candidates", [])

    logger.info("")
    logger.info("the request        %s", state["request"])
    logger.info("read as            %s", asked.model_dump(exclude_none=True, exclude={"request"}))
    logger.info("candidates         %s", ", ".join(found))

    logger.info("")
    logger.info(COLUMNS, "sku", "what it is", "total", "days", "approval", "risk", "strategies")
    for scenario, row in zip(state["scenarios"], builder.compare(state["scenarios"]), strict=True):
        logger.info(
            COLUMNS,
            ", ".join(row["skus"]),
            scenario.lines[0].description[:32],
            row["total"],
            row["days"],
            "needed" if row["needs_approval"] else "—",
            row["risk"],
            ", ".join(row["strategies"]),
        )

    for sku, refused in state["trace"]["validate"]["withheld"].items():
        logger.info("   ✘ %s withheld — %s", sku, "; ".join(refused))

    logger.info("")
    if state["recommendation"] is None:
        logger.info("no offer — %s", state["refused"])
        return

    written = state["recommendation"]
    logger.info("recommended        %s, after %d round(s)", written.sku, written.rounds_used)
    logger.info("because            %s", written.because)
    for condition in written.watch_out:
        logger.info("watch out          %s", condition)
    logger.info("")
    logger.info("%s", written.text)


def run(request: str, store: Store = Store.ATHENS) -> None:
    show(build_graph().invoke(make_initial_state(request, store)))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('say what to ask for:  python -m tools.run_offer "<request>" [store]')

    try:
        run(sys.argv[1], Store(sys.argv[2].upper()) if len(sys.argv) > 2 else Store.ATHENS)
    except STOPPED as exc:
        sys.exit(f"{type(exc).__name__}: {exc}")
