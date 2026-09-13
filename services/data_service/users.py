"""
Users
=====
Who may log in. Two demo accounts are written the first time the service starts against
an empty table, so a fresh clone has someone to log in as.
"""

import logging

from sqlalchemy.orm import Session

from services.data_service.models import User
from services.security import hash_password

logger = logging.getLogger(__name__)

# Demo accounts. The passwords are not secrets — the JWT key is.
DEMO_USERS = [
    ("maria", "agora-maria"),
    ("nikos", "agora-nikos"),
]


def get_user(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()


def seed_demo_users(db: Session) -> int:
    """Write the demo accounts, but only into a table that holds nobody yet.

    Returns:
        How many users were added — zero on every start after the first.
    """
    if db.query(User).first() is not None:
        return 0

    for username, password in DEMO_USERS:
        db.add(User(username=username, hashed_password=hash_password(password)))
    db.commit()

    logger.info("seeded %d demo users", len(DEMO_USERS))
    return len(DEMO_USERS)
