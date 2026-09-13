"""
Auth
====
Login, forwarded. The data service owns the users and issues the token; this route exists
so that the screen and Swagger talk to one origin.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from services.offer_service.clients import auth, catalog

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/login",
    summary="Log in through the data service",
    response_description="The data service's token, unchanged",
)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    """The OAuth2 password form goes to the data service as it is, and its token comes back as it is."""
    try:
        return auth.login(form.username, form.password)
    except auth.LoginRefused as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except catalog.CatalogueUnavailable as exc:
        logger.warning("login could not be forwarded — %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
