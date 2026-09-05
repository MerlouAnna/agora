"""
Settings
========
What the two services read from the environment, in one place. The values come from
`.env` at the repository root, which is not in version control — `.env.example` shows
what belongs in it.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Defaults are the values a clone can run with; only the API key has to be supplied."""

    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    catalog_service_url: str = "http://localhost:8001"

    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
