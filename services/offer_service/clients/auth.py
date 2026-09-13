"""
Auth client
===========
How the offer service logs a salesperson in: the form goes to the data service, which owns
the users, and the token it issues comes back unchanged.
"""

import logging

import httpx

from services.config import settings
from services.offer_service.clients.catalog import CatalogueUnavailable

logger = logging.getLogger(__name__)

TIMEOUT = 30.0


class LoginRefused(ValueError):
    """The data service did not accept the username and password."""


def login(username: str, password: str) -> dict:
    """The data service's answer to the password form, as it gave it.

    Raises:
        LoginRefused: Wrong username or password.
        CatalogueUnavailable: The data service is not running or refused the request.
    """
    with _http() as http:
        try:
            answer = http.post("/auth/login", data={"username": username, "password": password})
            if answer.status_code != 401:
                answer.raise_for_status()
        except httpx.HTTPError as exc:
            raise CatalogueUnavailable(f"login did not answer: {exc}") from exc

    if answer.status_code == 401:
        raise LoginRefused(answer.json().get("detail", "Incorrect username or password"))

    return answer.json()


def _http() -> httpx.Client:
    return httpx.Client(base_url=settings.catalog_service_url, timeout=TIMEOUT)
