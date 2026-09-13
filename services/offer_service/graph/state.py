"""
Graph state
===========
What travels from one node to the next: the request as it came in, what each step made of
it, and a trace that accumulates rather than being overwritten.
"""

import operator
from typing import Annotated, TypedDict

from services.data_service.delivery import Store
from services.offer_service.domain.models import OfferScenario
from services.offer_service.recommendation import Recommendation
from services.offer_service.requirements import CustomerRequirements
from services.offer_service.validation import ValidationReport


class OfferState(TypedDict):
    """One request on its way through the graph.

    `report` holds every scenario and its verdict; `report.offers` is the subset that may
    be shown, and it is the only thing the recommendation is given. `refused` is set when
    there is nothing to recommend, and says at which step the trail went cold.
    """

    request: str
    store: Store
    before_cut_off: bool
    requirements: CustomerRequirements | None
    products: list[dict]
    suppliers: dict[str, dict]
    scenarios: list[OfferScenario]
    report: ValidationReport | None
    recommendation: Recommendation | None
    refused: str | None
    trace: Annotated[dict, operator.or_]


def make_initial_state(
    request: str, store: Store = Store.ATHENS, before_cut_off: bool = True
) -> OfferState:
    """A fresh state for one request, with every field a node writes already present."""
    return {
        "request": request,
        "store": store,
        "before_cut_off": before_cut_off,
        "requirements": None,
        "products": [],
        "suppliers": {},
        "scenarios": [],
        "report": None,
        "recommendation": None,
        "refused": None,
        "trace": {},
    }
