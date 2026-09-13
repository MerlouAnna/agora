"""
Settings
========
What the two services read from the environment, in one place. The values come from
`.env` at the repository root, which is not in version control — `.env.example` shows
what belongs in it.
"""

import logging
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Defaults are the values a clone can run with; the two keys have to be supplied."""

    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    catalog_service_url: str = "http://localhost:8001"
    jwt_secret_key: str = ""
    access_token_expire_minutes: int = 480

    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()

_client = None


def key_source() -> str:
    """Where the API key actually came from.

    A variable already in the environment beats the file, which is the right order for a
    deployment and a trap on a laptop: a key left over from another project takes over
    silently and the errors that follow point at billing rather than at the key.
    """
    return "the environment" if os.environ.get("OPENAI_API_KEY") else str(ENV_FILE)


def key_fingerprint() -> str:
    """Enough of the key to recognise it, and nothing anyone can use."""
    key = settings.openai_api_key
    return f"{key[:11]}…{key[-4:]} ({len(key)} chars)" if key else "none"


def openai_client(unavailable: type[Exception]):
    """The OpenAI client, built once per process."""
    global _client

    if _client is None:
        if not settings.openai_api_key:
            raise unavailable("no OPENAI_API_KEY in the environment")

        logger.info(
            "loading the OpenAI client — key %s, read from %s",
            key_fingerprint(),
            key_source(),
        )
        from openai import OpenAI

        _client = OpenAI(api_key=settings.openai_api_key)

    return _client
