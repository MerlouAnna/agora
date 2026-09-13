"""
Assistant
=========
A salesperson's question in, an answer built from tool results out, and both written into
the conversation they belong to. The user comes from the token, and the history is only
ever read under that user's name.
"""

import logging

from fastapi import APIRouter, HTTPException, Path, status

from services.offer_service.assistant import graph as assistant
from services.offer_service.assistant import model
from services.offer_service.clients import catalog, history
from services.offer_service.dependencies import CurrentUser
from services.offer_service.rag import embeddings, retriever
from services.offer_service.schemas import AskAnswer, AskRequest, Thread, ThreadDetail, Turn

logger = logging.getLogger(__name__)

router = APIRouter()

# How many earlier turns the model is shown, so a follow-up reads as one conversation.
HISTORY_TURNS = 10

UNREACHABLE = (
    catalog.CatalogueUnavailable,
    embeddings.EmbeddingsUnavailable,
    model.ModelUnavailable,
    retriever.IndexNotBuilt,
)
REFUSED = (assistant.AssistantFailed,)

_graph = None


def graph():
    global _graph

    if _graph is None:
        _graph = assistant.build_graph()

    return _graph


@router.post(
    "/ask",
    response_model=AskAnswer,
    summary="Ask a question about the catalogue or the terms",
    response_description="The answer, and the tool calls it was built from",
)
def ask(asked: AskRequest, user: CurrentUser) -> AskAnswer:
    """
    The model chooses which tools to call — a product's stock, a search of one category, the
    business documents — and answers from what they return. Every code and figure in the
    answer is checked against those results; an answer that cannot be supported is sent back
    once and then refused, in words that say what could not be supported.

    The last turns of the conversation are handed to the model, so a follow-up reads as one.
    The question and the answer are both recorded. A refusal is a 200 that stays in the
    thread, because it is an answer; a model that never stopped calling tools is a 502 that
    leaves nothing behind, because it is a failure.
    """
    try:
        thread = asked.conversation_id
        if thread is None:
            thread = history.open_conversation(user)["id"]
        earlier = history.conversation(thread, user)["messages"][-HISTORY_TURNS:]

        answered = graph().invoke(
            assistant.make_initial_state(
                asked.question,
                [{"role": one["role"], "content": one["content"]} for one in earlier],
            )
        )
        answer = answered["refused"] if answered["answer"] is None else answered["answer"]

        history.add_message(thread, user, "user", asked.question)
        history.add_message(thread, user, "assistant", answer, answered["tools_used"])
    except history.ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except UNREACHABLE as exc:
        logger.warning("the question could not be answered — %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except REFUSED as exc:
        logger.warning("the model never produced an answer — %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return AskAnswer(
        conversation_id=thread,
        answer=answer,
        refused=answered["refused"] is not None,
        tools=answered["tools_used"],
        rounds=answered["rounds"],
    )


@router.get(
    "/conversations",
    response_model=list[Thread],
    summary="The user's conversations, newest first",
)
def list_conversations(user: CurrentUser) -> list[Thread]:
    try:
        threads = history.conversations(user)
    except catalog.CatalogueUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return [Thread(id=one["id"], started_at=one["started_at"]) for one in threads]


@router.get(
    "/conversations/{conversation_id}",
    response_model=ThreadDetail,
    summary="One conversation with every turn in it",
)
def read_conversation(user: CurrentUser, conversation_id: int = Path(ge=1)) -> ThreadDetail:
    try:
        thread = history.conversation(conversation_id, user)
    except history.ConversationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except catalog.CatalogueUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return ThreadDetail(
        id=thread["id"],
        started_at=thread["started_at"],
        messages=[Turn(**one) for one in thread["messages"]],
    )
