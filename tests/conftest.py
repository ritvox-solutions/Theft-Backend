import os

# Point the app at a dedicated test database *before* any app module is
# imported, so app.config's load_dotenv() (override=False) never clobbers it.
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://theft_user:theft_pass@localhost:5432/theft_test_db",
)

import pytest
from fastapi.testclient import TestClient

from app import models  # noqa: F401 — ensures all models are registered on Base.metadata
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.meter import Meter
from app.models.user import User, UserRole
from app.services.auth import create_access_token, hash_password


@pytest.fixture(scope="session", autouse=True)
def _tables():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture(autouse=True)
def _no_ml_model_by_default(monkeypatch):
    """Tests must not depend on whether a real model.pkl happens to exist on
    disk (it will, once train.py has been run for local dev/demo purposes).
    Default every test to "no model loaded"; test_ml.py's trained_test_model
    fixture opts back in explicitly where scoring behavior is under test."""
    from app.ml import predict

    monkeypatch.setattr(predict, "_model", None)


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seed_users_and_meters(db_session):
    """Two consumers (each with one meter) + one admin — the standard Phase 1 fixture set."""
    admin = User(
        name="Admin",
        email="admin@test.local",
        password_hash=hash_password("pw"),
        role=UserRole.admin,
    )
    consumer_a = User(
        name="Consumer A",
        email="a@test.local",
        password_hash=hash_password("pw"),
        role=UserRole.consumer,
    )
    consumer_b = User(
        name="Consumer B",
        email="b@test.local",
        password_hash=hash_password("pw"),
        role=UserRole.consumer,
    )
    db_session.add_all([admin, consumer_a, consumer_b])
    db_session.flush()

    meter_a = Meter(meter_code="MTR-A", user_id=consumer_a.id, device_key="KEY-A")
    meter_b = Meter(meter_code="MTR-B", user_id=consumer_b.id, device_key="KEY-B")
    db_session.add_all([meter_a, meter_b])
    db_session.commit()
    db_session.refresh(meter_a)
    db_session.refresh(meter_b)

    return {
        "admin": admin,
        "consumer_a": consumer_a,
        "consumer_b": consumer_b,
        "meter_a": meter_a,
        "meter_b": meter_b,
        "token_admin": create_access_token(admin),
        "token_a": create_access_token(consumer_a),
        "token_b": create_access_token(consumer_b),
    }
