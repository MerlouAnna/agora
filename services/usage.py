"""
Model usage
===========
Every call to a language or embedding model is written down here: what asked for it, which
model answered, how many tokens it took and how long. Nothing in the project talks to a
model without passing through `record`, so the totals are the whole bill and not a sample.

The rows live in the catalogue database, which is the only database the project has.
"""

import logging
from datetime import datetime

from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

# Dollars per million tokens, from OpenAI's public pricing (checked September 2026).
# Used only for the estimate the usage report shows; nothing depends on it being current.
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
}


def record(
    service: str,
    purpose: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_ms: int = 0,
    ok: bool = True,
    detail: str | None = None,
) -> None:
    """Write one call down.

    A failure to record is logged and swallowed: the usage log exists to be read later,
    and losing a row is never a reason to fail the work that was actually asked for.
    """
    from services.data_service.database import DB_PATH

    call = dict(
        called_at=datetime.now(),
        service=service,
        purpose=purpose,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        duration_ms=duration_ms,
        ok=ok,
        detail=detail,
    )

    try:
        _insert(call)
    except OperationalError:
        # The tools can run before the catalogue has been built, and a run that is about
        # to spend money should not be the one that finds the log has nowhere to go.
        _create_table()
        try:
            _insert(call)
        except Exception as exc:
            logger.warning("could not record model usage in %s: %s", DB_PATH, exc)
    except Exception as exc:
        logger.warning("could not record model usage in %s: %s", DB_PATH, exc)


def _insert(call: dict) -> None:
    from services.data_service.database import SessionLocal
    from services.data_service.models import LlmCall

    with SessionLocal() as db:
        db.add(LlmCall(**call))
        db.commit()


def _create_table() -> None:
    from services.data_service.database import engine
    from services.data_service.models import LlmCall

    logger.info("creating the llm_calls table")
    LlmCall.__table__.create(bind=engine, checkfirst=True)


def cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """What those tokens are worth in dollars, or 0.0 for a model with no price on file."""
    if model not in PRICES:
        return 0.0

    in_price, out_price = PRICES[model]
    return round(
        (prompt_tokens * in_price + completion_tokens * out_price) / 1_000_000, 6
    )
