"""Seed the database with demo users and meters. Run with `python -m app.seed`.

Safe to re-run: existing users/meters (matched by email / meter_code) are left alone.
"""

from app import models  # noqa: F401 — ensures all models are registered on Base.metadata
from app.database import Base, SessionLocal, engine
from app.models.meter import Meter
from app.models.user import User, UserRole
from app.services.auth import hash_password

SEED_PASSWORD = "Password123!"

ADMINS = [
    {"name": "Admin One", "email": "admin1@gridwatch.test"},
    {"name": "Admin Two", "email": "admin2@gridwatch.test"},
]

CONSUMERS = [
    {"name": "Consumer One", "email": "consumer1@gridwatch.test"},
    {"name": "Consumer Two", "email": "consumer2@gridwatch.test"},
    {"name": "Consumer Three", "email": "consumer3@gridwatch.test"},
    {"name": "Consumer Four", "email": "consumer4@gridwatch.test"},
    {"name": "Consumer Five", "email": "consumer5@gridwatch.test"},
]


def get_or_create_user(db, name: str, email: str, role: UserRole) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(name=name, email=email, password_hash=hash_password(SEED_PASSWORD), role=role)
    db.add(user)
    db.flush()
    return user


def get_or_create_meter(db, meter_code: str, user_id, device_key: str) -> Meter:
    meter = db.query(Meter).filter(Meter.meter_code == meter_code).first()
    if meter:
        return meter
    meter = Meter(
        meter_code=meter_code,
        user_id=user_id,
        device_key=device_key,
        location_label=f"Location for {meter_code}",
    )
    db.add(meter)
    db.flush()
    return meter


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        admin_users = [
            get_or_create_user(db, admin["name"], admin["email"], UserRole.admin)
            for admin in ADMINS
        ]

        for i, consumer in enumerate(CONSUMERS, start=1):
            user = get_or_create_user(db, consumer["name"], consumer["email"], UserRole.consumer)
            get_or_create_meter(db, f"MTR-{i:04d}", user.id, f"DEVKEY-{i:04d}")

        # Dedicated, admin-owned reference meter for ML training data — not one
        # of the 5 consumer demo meters, kept clean of any manually-injected
        # anomalous test data. See app/scripts/seed_training_data.py.
        get_or_create_meter(db, "MTR-TRAIN", admin_users[0].id, "DEVKEY-TRAIN")

        db.commit()
        print(f"Seeded {len(ADMINS)} admins, {len(CONSUMERS)} consumers, {len(CONSUMERS)} meters.")
        print("Plus 1 admin-owned MTR-TRAIN reference meter for ML training data.")
        print(f"All seeded users share the password: {SEED_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
