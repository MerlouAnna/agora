"""
Graph builder
=============
The workflow wired up and compiled: extract, retrieve, build, check, and then either a
recommendation or the reason there is none.
"""

import logging

from langgraph.graph import END, START, StateGraph

from services.offer_service.graph.nodes import (
    build_scenarios,
    extract,
    no_valid_offer,
    recommend,
    retrieve,
    route_after_validation,
    validate,
)
from services.offer_service.graph.state import OfferState

logger = logging.getLogger(__name__)


def build_graph():
    """Compile the workflow.

    START → extract → retrieve → build_scenarios → validate, and from there to either
    recommend or no_valid_offer. The earlier steps have no fork of their own: a search
    that finds nothing builds nothing and checks nothing, and the one conditional at the
    end is what says so.

    Returns:
        The compiled graph, ready to `invoke()` a state from `make_initial_state`.
    """
    graph = StateGraph(OfferState)

    graph.add_node("extract", extract)
    graph.add_node("retrieve", retrieve)
    graph.add_node("build_scenarios", build_scenarios)
    graph.add_node("validate", validate)
    graph.add_node("recommend", recommend)
    graph.add_node("no_valid_offer", no_valid_offer)

    graph.add_edge(START, "extract")
    graph.add_edge("extract", "retrieve")
    graph.add_edge("retrieve", "build_scenarios")
    graph.add_edge("build_scenarios", "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validation,
        {"recommend": "recommend", "no_valid_offer": "no_valid_offer"},
    )
    graph.add_edge("recommend", END)
    graph.add_edge("no_valid_offer", END)

    logger.info("the offer graph is compiled — six nodes, one fork")
    return graph.compile()
