"""
History
=======
The conversations a salesperson has had with the assistant, one thread per login. Every
read is scoped by username, so a thread is only ever found by the person it belongs to.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from services.data_service.models import Conversation, Message

logger = logging.getLogger(__name__)


def open_conversation(db: Session, username: str) -> Conversation:
    thread = Conversation(username=username, started_at=datetime.now())
    db.add(thread)
    db.commit()
    db.refresh(thread)

    logger.info("%s opened conversation %d", username, thread.id)
    return thread


def list_conversations(db: Session, username: str) -> list[Conversation]:
    return (
        db.query(Conversation)
        .filter(Conversation.username == username)
        .order_by(Conversation.started_at.desc())
        .all()
    )


def get_conversation(db: Session, conversation_id: int, username: str) -> Conversation | None:
    return (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.username == username)
        .first()
    )


def get_messages(db: Session, conversation_id: int) -> list[Message]:
    return (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id)
        .all()
    )


def add_message(
    db: Session, conversation_id: int, role: str, content: str, tools: list | None = None
) -> Message:
    """Append one turn. The caller has already checked the thread is the user's own."""
    said = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        tools=tools,
        created_at=datetime.now(),
    )
    db.add(said)
    db.commit()
    db.refresh(said)

    return said
