"""
Dependencies
============
Who is asking. The token was issued by the data service at login; this side only checks
the signature with the shared secret and reads the username out of it. No table is read.
"""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from services import security
from services.config import settings

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.catalog_service_url}/auth/login")


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> str:
    """The username the bearer token names, or 401."""
    try:
        return security.token_subject(token)
    except security.InvalidToken as exc:
        logger.info("a request carried a token that could not be trusted — %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except security.SecretMissing as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


CurrentUser = Annotated[str, Depends(get_current_user)]
