import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services import security
from services.config import settings
from services.data_service.database import get_db
from services.data_service.main import app
from services.data_service.models import TableBase, User
from services.data_service.users import DEMO_USERS, seed_demo_users

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

USERNAME, PASSWORD = DEMO_USERS[0]


@pytest.fixture(scope="module", autouse=True)
def accounts():
    TableBase.metadata.create_all(bind=engine)
    with TestingSession() as db:
        seed_demo_users(db)

    app.dependency_overrides[get_db] = lambda: TestingSession()
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", "test-only")


client = TestClient(app)


def test_login_returns_a_token_that_names_the_user():
    answered = client.post("/auth/login", data={"username": USERNAME, "password": PASSWORD})
    body = answered.json()

    assert answered.status_code == 200
    assert body["token_type"] == "bearer"
    assert security.token_subject(body["access_token"]) == USERNAME


def test_a_wrong_password_is_401_and_says_no_more_than_that():
    answered = client.post("/auth/login", data={"username": USERNAME, "password": "nope"})

    assert answered.status_code == 401
    assert answered.headers["WWW-Authenticate"] == "Bearer"
    assert answered.json()["detail"] == "Incorrect username or password"


def test_the_seed_fills_an_empty_table_and_leaves_a_full_one_alone():
    fresh = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    TableBase.metadata.create_all(bind=fresh)

    with sessionmaker(bind=fresh)() as db:
        assert seed_demo_users(db) == len(DEMO_USERS)
        assert seed_demo_users(db) == 0
        rows = db.query(User).all()

    assert len(rows) == len(DEMO_USERS)
    assert all(row.hashed_password != PASSWORD for row in rows)
