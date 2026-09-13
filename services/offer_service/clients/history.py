"""
History client
==============
How the offer service reads and writes the assistant's conversations: over HTTP to the data
service, always under the username the token named. The browser never reaches these routes.
"""

import logging

import httpx

from services.config import settings
from services.offer_service.clients.catalog import CatalogueUnavailable

logger = logging.getLogger(__name__)

TIMEOUT = 30.0


class ConversationNotFound(LookupError):
    """No such conversation, or not this user's."""


def open_conversation(username: str) -> dict:
    with _http() as http:
        try:
            answer = http.post("/conversations", json={"username": username})
            answer.raise_for_status()
        except httpx.HTTPError as exc:
            raise CatalogueUnavailable(f"could not open a conversation: {exc}") from exc

    logger.info("%s opened conversation %s", username, answer.json()["id"])
    return answer.json()


def conversations(username: str) -> list[dict]:
    """The user's conversations, newest first."""
    with _http() as http:
        try:
            answer = http.get("/conversations", params={"username": username})
            answer.raise_for_status()
        except httpx.HTTPError as exc:
            raise CatalogueUnavailable(f"the conversations did not answer: {exc}") from exc

    return answer.json()


def conversation(conversation_id: int, username: str) -> dict:
    """One conversation with every turn in it.

    Raises:
        ConversationNotFound: No such thread, or it belongs to someone else.
        CatalogueUnavailable: The service is not running or refused the request.
    """
    with _http() as http:
        return _owned(http, "GET", f"/conversations/{conversation_id}", username)


def add_message(
    conversation_id: int, username: str, role: str, content: str, tools: list | None = None
) -> dict:
    with _http() as http:
        return _owned(
            http,
            "POST",
            f"/conversations/{conversation_id}/messages",
            username,
            json={"role": role, "content": content, "tools": tools},
        )


def _owned(http: httpx.Client, method: str, path: str, username: str, **request) -> dict:
    """A request about one conversation, under one name. A 404 is the thread not being theirs."""
    try:
        answer = http.request(method, path, params={"username": username}, **request)
        if answer.status_code != 404:
            answer.raise_for_status()
    except httpx.HTTPError as exc:
        raise CatalogueUnavailable(f"{path} did not answer: {exc}") from exc

    if answer.status_code == 404:
        raise ConversationNotFound(f"{path} is not {username}'s")

    return answer.json()


def _http() -> httpx.Client:
    return httpx.Client(base_url=settings.catalog_service_url, timeout=TIMEOUT)
