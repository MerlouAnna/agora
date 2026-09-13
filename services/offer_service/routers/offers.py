"""
Offers
======
The one path the service exists for: a sentence a salesperson wrote down goes in, and
everything the graph made of it comes back.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from services.offer_service import extraction, recommendation
from services.offer_service import scenario_builder as builder
from services.offer_service.clients import catalog
from services.offer_service.dependencies import CurrentUser
from services.offer_service.graph.builder import build_graph
from services.offer_service.graph.state import make_initial_state
from services.offer_service.rag import embeddings, retriever
from services.offer_service.schemas import (
    Checked,
    CheckResult,
    ComparedOffer,
    OfferAnswer,
    OfferRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Something the request depends on is not answering, as against the model refusing to.
UNREACHABLE = (
    catalog.CatalogueUnavailable,
    embeddings.EmbeddingsUnavailable,
    extraction.ModelUnavailable,
    recommendation.ModelUnavailable,
    retriever.IndexNotBuilt,
)
REFUSED = (extraction.ExtractionFailed, recommendation.RecommendationFailed)

_graph = None


def graph():
    """The compiled workflow, built once. Compiling it per request buys nothing."""
    global _graph

    if _graph is None:
        _graph = build_graph()

    return _graph


@router.post(
    "/generate",
    response_model=OfferAnswer,
    summary="Turn a request into offers and a recommendation",
    response_description="The offers, the answer, and the working behind both",
)
def generate(asked: OfferRequest, user: CurrentUser) -> OfferAnswer:
    """
    Read the request, search the catalogue, price five readings of it, check every figure,
    and recommend one — or say why there is nothing to recommend.

    The path is synchronous on purpose: it calls the model twice and the catalogue three
    times, and FastAPI runs a plain `def` in a worker thread rather than on the loop.
    """
    state = make_initial_state(asked.request, asked.store, asked.before_cut_off)

    try:
        answered = graph().invoke(state)
    except UNREACHABLE as exc:
        logger.warning("the request could not be answered — %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except REFUSED as exc:
        logger.warning("the model never produced an answer — %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return _answer(answered)


def _answer(state: dict) -> OfferAnswer:
    """The graph's state as the salesperson's screen reads it."""
    report = state["report"]
    written = state["recommendation"]

    return OfferAnswer(
        requirements=state["requirements"].model_dump(exclude_none=True),
        offers=[ComparedOffer(**row) for row in builder.compare(report.offers)],
        recommendation=written.model_dump() if written is not None else None,
        refused=state["refused"],
        checked=[
            Checked(
                sku=verdict.scenario.lines[0].sku,
                offerable=verdict.offerable,
                failed=[
                    CheckResult(
                        name=check.name,
                        severity=check.severity.value,
                        passed=check.passed,
                        said=check.said,
                    )
                    for check in verdict.failed
                ],
            )
            for verdict in report.verdicts
        ],
        trace=state["trace"],
    )
