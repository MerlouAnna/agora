"""
Retrieval
=========
The products a request should be shown: narrowed by its constraints — loosened by one of
them when nothing survives — then found twice over the same cards, by meaning and by word,
merged and priced from the catalogue. The same two halves answer a question put to the
business documents.
"""

import logging
from dataclasses import dataclass
from itertools import zip_longest

from services.data_service.categories import ORDERED_LABELS
from services.offer_service.clients import catalog
from services.offer_service.rag import embeddings, filters, lexical, store
from services.offer_service.requirements import Constraint, CustomerRequirements, Ordering

logger = logging.getLogger(__name__)

REQUEST = "customer-request"
QUESTION = "policy-question"

CANDIDATES = 50


class IndexNotBuilt(RuntimeError):
    """The collection holds nothing, so an empty answer would mean the wrong thing."""


@dataclass(frozen=True)
class Match:
    """One product a request reached, as the catalogue prices and counts it right now."""

    sku: str
    card: str
    metadata: dict
    price: float | None
    stock: int | None


@dataclass(frozen=True)
class Retrieval:
    """What came back, and enough of how it was found to explain it."""

    matches: list[Match]
    trace: dict


@dataclass(frozen=True)
class Excerpt:
    """One section of one business document, as a question gets it back."""

    id: str
    text: str
    metadata: dict


def candidates(requirements: CustomerRequirements, limit: int = CANDIDATES) -> tuple[list, dict]:
    """The codes a request reaches, best first, without asking the catalogue anything.

    Args:
        requirements: The request, with whatever constraints were pulled out of it.
        limit: How many codes to keep.

    Returns:
        The codes and a trace of what each half of the search proposed.

    Raises:
        IndexNotBuilt: Nothing is indexed, which is not the same as nothing matching.
        EmbeddingsUnavailable: The request could not be embedded.
    """
    products = _built()
    where = filters.where(requirements)
    eligible = products.get(where=where, include=["documents", "metadatas"])
    codes = list(eligible["ids"])
    trace: dict = {"eligible": len(codes), "filter": where}

    if not codes and requirements.constraints:
        reached, given = _relaxed(products, requirements)
        where = {"sku": {"$in": reached}} if reached else where
        eligible = products.get(where=where, include=["documents", "metadatas"])
        codes = list(eligible["ids"])
        trace |= {"eligible": len(codes), "filter": where} | given
        logger.info(
            "nothing satisfied the request — %d products are one concession away", len(codes)
        )

    if not codes:
        logger.info("nothing to search — the model was not asked for a vector")
        return [], trace

    if requirements.order is not None:
        ordered = _at_the_end(requirements.order, codes, eligible["metadatas"] or [])[:limit]
        order = requirements.order
        trace |= {"ordered_by": f"{order.key} {order.end}", "merged": ordered}
        return ordered, trace

    by_word = lexical.ranked(requirements.request, codes, list(eligible["documents"] or []))
    by_meaning = _by_meaning(products, requirements.request, where, len(codes))
    ordered = _merged(by_word, by_meaning)[:limit]

    trace |= {"by_word": by_word[:limit], "by_meaning": by_meaning[:limit], "merged": ordered}
    return ordered, trace


def search(requirements: CustomerRequirements, limit: int = 10) -> Retrieval:
    """The same products, priced and counted as the catalogue has them right now.

    Raises:
        CatalogueUnavailable: What was found could not be priced.
    """
    ordered, trace = candidates(requirements, limit)
    if not ordered:
        return Retrieval([], trace)

    held = _built().get(ids=ordered, include=["documents", "metadatas"])
    cards = dict(
        zip(
            held["ids"],
            zip(held["documents"] or [], held["metadatas"] or [], strict=True),
            strict=True,
        )
    )
    return Retrieval(_priced(ordered, cards), trace)


def search_policies(question: str, limit: int = 5) -> tuple[list[Excerpt], dict]:
    """The sections of the business documents that answer a question about the terms.

    Nothing is filtered out first. A datasheet section carries the code of the product it
    describes in its own text, so a question naming one finds it by name.

    Args:
        question: What the salesperson, or the graph on their behalf, wants to know.
        limit: How many sections to hand back.

    Returns:
        The sections and a trace of what each half of the search proposed.

    Raises:
        IndexNotBuilt: The documents have not been indexed.
        EmbeddingsUnavailable: The question could not be embedded.
    """
    passages = _built(store.POLICIES)
    held = passages.get(include=["documents", "metadatas"])
    codes = list(held["ids"])
    texts = list(held["documents"] or [])

    by_word = lexical.ranked(question, codes, texts)
    by_meaning = _by_meaning(passages, question, None, len(codes), QUESTION)
    ordered = _merged(by_word, by_meaning)[:limit]

    sections = dict(zip(codes, zip(texts, held["metadatas"] or [], strict=True), strict=True))
    trace = {
        "passages": len(codes),
        "by_word": by_word[:limit],
        "by_meaning": by_meaning[:limit],
        "merged": ordered,
    }
    found = [
        Excerpt(id=code, text=sections[code][0], metadata=dict(sections[code][1]))
        for code in ordered
    ]
    return found, trace


def _relaxed(products, requirements: CustomerRequirements) -> tuple[list[str], dict]:
    """Everything that is one concession away, and which concession each product costs.

    Choosing between them is not this service's business. A switch with fewer ports but the
    PoE the customer asked for, and a switch with the ports but no PoE, are two offers to
    put in front of a salesperson, not a right answer and a wrong one.
    """
    opened: dict[str, list[str]] = {}
    for n, constraint in enumerate(requirements.constraints):
        clause = _without(requirements, n)
        opened[_written(constraint)] = list(products.get(where=clause, include=[])["ids"])

    reached: dict[str, None] = {}
    for found in opened.values():
        for code in found:
            reached.setdefault(code)

    if reached:
        return list(reached), {"concessions": {c: f for c, f in opened.items() if f}}

    everything = range(len(requirements.constraints))
    clause = _without(requirements, *everything)
    found = list(products.get(where=clause, include=[])["ids"])
    return found, {"concessions": {"every constraint": found} if found else {}}


def _without(requirements: CustomerRequirements, *dropped: int) -> dict | None:
    kept = [c for n, c in enumerate(requirements.constraints) if n not in dropped]
    return filters.where(requirements.model_copy(update={"constraints": kept}))


def _written(constraint: Constraint) -> str:
    """The constraint as the trace shows it, and as an explanation would read it out."""
    value = constraint.value
    if isinstance(value, float) and value.is_integer():
        value = int(value)

    return f"{constraint.key} {constraint.op} {value}"


def _built(name: str = store.PRODUCTS):
    collection = store.collection(name)
    if collection.count() == 0:
        raise IndexNotBuilt(f"the {name} collection is empty — run the indexer first")

    return collection


def _at_the_end(order: Ordering, codes: list[str], metadata: list) -> list[str]:
    """The eligible products sorted at the end of the range the request named.

    "The longest cable you have" is a question the catalogue answers exactly; asking either
    ranking to guess it is asking the wrong thing. Products with no such specification go
    last rather than being dropped.
    """
    held = dict(zip(codes, metadata, strict=True))
    known = [code for code in codes if held[code].get(order.key) is not None]
    away = -1 if order.end == "max" else 1

    ranked = sorted(known, key=lambda code: (away * _place(order.key, held[code][order.key]), code))
    return ranked + [code for code in codes if code not in set(known)]


def _place(key: str, value) -> float:
    if key in ORDERED_LABELS:
        return float(ORDERED_LABELS[key].index(value))
    return float(value)


def _by_meaning(
    products, request: str, where: dict | None, eligible: int, purpose: str = REQUEST
) -> list[str]:
    """Everything eligible, nearest first — both rankings cover the same set.

    The two are taken in turn, so cutting one of them short would hand its tail to the
    other half alone rather than to both.
    """
    vector = embeddings.embed([request], purpose)[0]
    found = products.query(
        query_embeddings=[list(vector)], where=where, n_results=eligible, include=[]
    )
    return list(found["ids"][0])


def _merged(*rankings: list[str]) -> list[str]:
    """One from each ranking in turn, so neither half can bury what the other put first.

    Scoring the two together — reciprocal rank fusion — was measured on both collections
    and lost a right answer each time: whenever only one half finds it, the other half's
    near misses outscore it. Taking turns costs each half nothing better than second place.
    """
    merged: dict[str, None] = {}
    for places in zip_longest(*rankings):
        for code in places:
            if code is not None:
                merged.setdefault(code)

    return list(merged)


def _priced(codes: list[str], held: dict) -> list[Match]:
    current = {row["sku"]: row for row in catalog.lookup(codes)}

    gone = [code for code in codes if code not in current]
    if gone:
        logger.warning("the catalogue no longer has %s — the index is behind", ", ".join(gone))

    return [
        Match(
            sku=code,
            card=held[code][0],
            metadata=dict(held[code][1]),
            price=current.get(code, {}).get("price"),
            stock=current.get(code, {}).get("stock_total"),
        )
        for code in codes
    ]
