"""
Auth
====
Login on the OAuth2 password form. A good username and password come back as a bearer
token; anything else is a 401 that does not say which half was wrong.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from services import security
from services.data_service import users
from services.data_service.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

db_dependency = Annotated[Session, Depends(get_db)]


@router.post(
    "/login",
    summary="Log in and receive a bearer token",
    response_description="The access token and its type",
)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: db_dependency):
    """
    OAuth2 password flow: send `username` and `password` as form fields and use the
    token that comes back as `Authorization: Bearer …`. The Swagger "Authorize" button
    does exactly this.
    """
    user = users.get_user(db, form.username)
    if user is None or not security.verify_password(form.password, str(user.hashed_password)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        token = security.create_access_token(str(user.username))
    except security.SecretMissing as exc:
        logger.error("login refused — %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    logger.info("%s logged in", user.username)
    return {"access_token": token, "token_type": "bearer"}
