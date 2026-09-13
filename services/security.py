"""
Security
========
Password hashes and the signed token both services agree on. The data service issues
the token at login; the offer service only reads it, with the same secret from `.env`.
"""

import logging
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from services.config import settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"


class SecretMissing(RuntimeError):
    """No JWT secret in the environment, so nothing can be signed or trusted."""


class InvalidToken(ValueError):
    """The token is malformed, expired, signed with another key, or names nobody."""


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def verify_password(raw: str, hashed: str) -> bool:
    return bcrypt.checkpw(raw.encode(), hashed.encode())


def create_access_token(sub: str) -> str:
    """A signed token naming one user, good for as long as the settings say."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": sub, "exp": expire}, _secret(), algorithm=ALGORITHM)


def token_subject(token: str) -> str:
    """Who a token names, if it was signed here and has not expired.

    Raises:
        InvalidToken: The token cannot be trusted, whatever the reason.
        SecretMissing: There is no secret to check it against.
    """
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except JWTError as exc:
        raise InvalidToken(str(exc)) from exc

    username = payload.get("sub")
    if not username:
        raise InvalidToken("the token names nobody")

    return str(username)


def _secret() -> str:
    if not settings.jwt_secret_key:
        raise SecretMissing("no JWT_SECRET_KEY in the environment")

    return settings.jwt_secret_key
