"""
Catalogue client
================
How the offer service reads the catalogue: over HTTP, exactly the way anything else
would. It holds no session, imports no model and knows no table — if the catalogue moves
to another machine tomorrow, this file is the only thing that changes.
"""

import logging

import httpx

from services.config import settings

logger = logging.getLogger(__name__)

PAGE = 100
TIMEOUT = 30.0


class CatalogueUnavailable(RuntimeError):
    """The catalogue service did not answer."""


def fetch_all() -> list[dict]:
    """Every product in the catalogue, read a page at a time.

    Returns:
        Products in SKU order, each with its specs, price and stock total.

    Raises:
        CatalogueUnavailable: The service is not running or refused the request.
    """
    products: list[dict] = []
    offset = 0

    with _http() as http:
        while True:
            page = _get(http, "/products/search", {"limit": PAGE, "offset": offset})
            products.extend(page)
            if len(page) < PAGE:
                break
            offset += PAGE

    logger.info("read %d products from %s", len(products), settings.catalog_service_url)
    return products


def stats() -> dict:
    """The catalogue's own count of what it holds, in one call."""
    with _http() as http:
        try:
            answer = http.get("/stats")
            answer.raise_for_status()
        except httpx.HTTPError as exc:
            raise CatalogueUnavailable(f"stats failed: {exc}") from exc

    return answer.json()


def lookup(skus: list[str]) -> list[dict]:
    """The current state of several products, priced and counted as of right now."""
    if not skus:
        return []

    with _http() as http:
        try:
            answer = http.post("/products/lookup", json={"skus": skus})
            answer.raise_for_status()
        except httpx.HTTPError as exc:
            raise CatalogueUnavailable(f"lookup failed: {exc}") from exc

    return answer.json()


def _http() -> httpx.Client:
    return httpx.Client(base_url=settings.catalog_service_url, timeout=TIMEOUT)


def _get(http: httpx.Client, path: str, params: dict) -> list[dict]:
    try:
        answer = http.get(path, params=params)
        answer.raise_for_status()
    except httpx.HTTPError as exc:
        raise CatalogueUnavailable(
            f"{settings.catalog_service_url}{path} did not answer: {exc}"
        ) from exc

    return answer.json()
