"""
Embeddings
==========
The one place text becomes a vector.

Chroma will happily embed for us, and we do it here instead: every model call in this
project is written down, and a call made inside the store is a call nobody sees on the
usage report. The store is handed finished vectors and never talks to OpenAI at all.
"""

import logging
import time
from collections.abc import Sequence

from services import config, usage
from services.config import settings

logger = logging.getLogger(__name__)

SERVICE = "offer_service"

BATCH = 100

_client = None


class EmbeddingsUnavailable(RuntimeError):
    """The embedding model could not be reached."""


def embed(texts: list[str], purpose: str) -> list[Sequence[float]]:
    """Vectors for these texts, in the order given.

    Args:
        texts: What to embed. A card, a document chunk, or one salesperson's request.
        purpose: What asked for them, as it will appear on the usage report.

    Returns:
        One vector per text.

    Raises:
        EmbeddingsUnavailable: The key is missing or the model did not answer.
    """
    vectors: list[Sequence[float]] = []
    for start in range(0, len(texts), BATCH):
        vectors.extend(_ask_model(texts[start : start + BATCH], purpose))

    return vectors


def client():
    """The OpenAI client, built once per process."""
    global _client

    if _client is None:
        if not settings.openai_api_key:
            raise EmbeddingsUnavailable("no OPENAI_API_KEY in the environment")

        logger.info(
            "loading the OpenAI client — key %s, read from %s",
            config.key_fingerprint(),
            config.key_source(),
        )
        from openai import OpenAI

        _client = OpenAI(api_key=settings.openai_api_key)
        logger.info("client ready, embedding with %s", settings.embedding_model)

    return _client


def _ask_model(texts: list[str], purpose: str) -> list[list[float]]:
    talk = client()

    started = time.monotonic()
    try:
        answer = talk.embeddings.create(model=settings.embedding_model, input=texts)
    except Exception as exc:
        usage.record(
            SERVICE,
            purpose,
            settings.embedding_model,
            duration_ms=_elapsed(started),
            ok=False,
            detail=str(exc)[:300],
        )
        raise EmbeddingsUnavailable(f"{settings.embedding_model} did not answer: {exc}") from exc

    spent = answer.usage
    usage.record(
        SERVICE,
        purpose,
        answer.model,
        prompt_tokens=spent.prompt_tokens if spent else 0,
        duration_ms=_elapsed(started),
    )

    return [item.embedding for item in answer.data]


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
