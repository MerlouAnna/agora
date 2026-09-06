"""
Facet filter
============
The constraints of a request, written as the metadata filter the store understands, so a
vector is only ever compared against products that already qualify.
"""

from services.data_service.categories import ORDERED_LABELS, ranked
from services.offer_service.requirements import Constraint, CustomerRequirements

CHROMA = {"eq": "$eq", "gte": "$gte", "lte": "$lte", "gt": "$gt", "lt": "$lt"}


def where(requirements: CustomerRequirements) -> dict | None:
    """The filter for these requirements, or None when nothing in them narrows the search.

    Price and stock are not in it: neither is indexed, and both are read from the catalogue
    at the moment the offer is built rather than at the moment a product is found.
    """
    clauses = []

    if requirements.category is not None:
        clauses.append({"category": {"$eq": requirements.category.value}})
    clauses.extend(_clause(constraint) for constraint in requirements.constraints)

    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _clause(constraint: Constraint) -> dict:
    if constraint.key in ORDERED_LABELS:
        return {constraint.key: {"$in": ranked(constraint.key, constraint.value, constraint.op)}}
    return {constraint.key: {CHROMA[constraint.op]: constraint.value}}
