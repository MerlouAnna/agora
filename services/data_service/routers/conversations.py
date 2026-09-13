"""
Conversations
=============
The assistant's history, kept here because this is where the database is. The routes are
internal: the offer service calls them with the username it read out of the token, and
nothing on this port is reached from the browser.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session
from starlette import status

from services.data_service import history
from services.data_service.database import get_db
from services.data_service.schemas import (
    ConversationDetail,
    ConversationOpen,
    ConversationSummary,
    MessageIn,
    MessageOut,
)

router = APIRouter()

db_dependency = Annotated[Session, Depends(get_db)]


@router.post(
    "",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Open a conversation for a user",
)
def open_conversation(db: db_dependency, asked: ConversationOpen):
    return history.open_conversation(db, asked.username)


@router.get(
    "",
    response_model=list[ConversationSummary],
    summary="A user's conversations, newest first",
)
def list_conversations(db: db_dependency, username: str = Query(min_length=1)):
    return history.list_conversations(db, username)


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetail,
    summary="One conversation with every turn in it",
)
def read_conversation(
    db: db_dependency, username: str = Query(min_length=1), conversation_id: int = Path(ge=1)
):
    """The thread and its messages in order. Another user's thread is a 404, not a 403."""
    thread = _owned(db, conversation_id, username)

    return ConversationDetail(
        id=thread.id,
        username=thread.username,
        started_at=thread.started_at,
        messages=history.get_messages(db, thread.id),
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="Append a turn to a conversation",
)
def add_message(
    db: db_dependency,
    said: MessageIn,
    username: str = Query(min_length=1),
    conversation_id: int = Path(ge=1),
):
    thread = _owned(db, conversation_id, username)

    return history.add_message(db, thread.id, said.role, said.content, said.tools)


def _owned(db: Session, conversation_id: int, username: str):
    thread = history.get_conversation(db, conversation_id, username)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    return thread
