"""
Assistant model call
====================
One round with the model: the conversation so far, the three tools it may ask for, and
whatever it answers — a tool request or words. Recorded like every other call.
"""

import logging
import time

from services import config, usage
from services.config import settings
from services.offer_service.assistant.tools import SCHEMAS

logger = logging.getLogger(__name__)

SERVICE = "offer_service"
PURPOSE = "assistant"
TEMPERATURE = 0.0

TOOLS = [
    {"type": "function", "function": {"name": name} | schema} for name, schema in SCHEMAS.items()
]


class ModelUnavailable(RuntimeError):
    """The assistant's model could not be reached."""


def complete(messages: list[dict]) -> dict:
    """One call, with the tools on offer.

    Args:
        messages: The instructions, the earlier turns, and everything said this turn.

    Returns:
        The assistant message as a dict the next call can be handed back: `role` and
        `content`, plus `tool_calls` when the model asked for a tool instead of answering.

    Raises:
        ModelUnavailable: The model did not answer.
    """
    talk = config.openai_client(ModelUnavailable)

    started = time.monotonic()
    try:
        completion = talk.chat.completions.create(
            model=settings.llm_model,
            temperature=TEMPERATURE,
            messages=messages,
            tools=TOOLS,
        )
    except Exception as exc:
        usage.record(
            SERVICE,
            PURPOSE,
            settings.llm_model,
            duration_ms=_elapsed(started),
            ok=False,
            detail=str(exc)[:300],
        )
        raise ModelUnavailable(f"{settings.llm_model} did not answer: {exc}") from exc

    spent = completion.usage
    usage.record(
        SERVICE,
        PURPOSE,
        completion.model,
        prompt_tokens=spent.prompt_tokens if spent else 0,
        completion_tokens=spent.completion_tokens if spent else 0,
        duration_ms=_elapsed(started),
    )

    message = completion.choices[0].message
    reply: dict = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        reply["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.function.name, "arguments": call.function.arguments},
            }
            for call in message.tool_calls
        ]

    return reply


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
