import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sklearn.ensemble import IsolationForest

from app.ml import predict
from app.ml.features import extract_features
from app.models.anomaly import Anomaly, AnomalyStatus
from app.models.reading_window import ReadingWindow
from app.services.aggregation import floor_to_window


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _reading_body(meter_code: str, voltage: float, current: float, ts: datetime) -> dict:
    return {
        "meter_id": meter_code,
        "voltage": voltage,
        "current": current,
        "timestamp": ts.isoformat(),
    }


def make_window(
    avg_voltage: float,
    avg_current: float,
    power_variance: float = 1.0,
    reading_count: int = 5,
    window_start: datetime | None = None,
) -> ReadingWindow:
    """A transient (non-persisted) ReadingWindow — enough for extract_features()."""
    window_start = window_start or datetime.now(timezone.utc)
    avg_power = avg_voltage * avg_current
    return ReadingWindow(
        meter_id=uuid.uuid4(),
        window_start=window_start,
        window_end=window_start + timedelta(minutes=15),
        avg_voltage=avg_voltage,
        avg_current=avg_current,
        avg_power=avg_power,
        power_variance=power_variance,
        reading_count=reading_count,
        energy_kwh=avg_power * 0.25 / 1000,
        is_anomaly=False,
        anomaly_score=None,
        scored_at=None,
    )


@pytest.fixture()
def trained_test_model(monkeypatch):
    """Fits a small IsolationForest on synthetic normal windows and installs it
    as app.ml.predict's module-level model for the duration of the test —
    decouples ML tests from the dev DB / MTR-TRAIN seed data entirely, while
    still exercising the real score_window()/extract_features() code paths."""
    rng = random.Random(42)
    windows = []
    for i in range(200):
        voltage = rng.gauss(230, 5)
        current = rng.gauss(10, 2)
        ts = datetime.now(timezone.utc) - timedelta(minutes=15 * i)
        windows.append(
            make_window(voltage, current, power_variance=rng.uniform(0.5, 5), window_start=ts)
        )

    X = [extract_features(w) for w in windows]
    model = IsolationForest(contamination=0.05, n_estimators=100, random_state=42)
    model.fit(X)

    monkeypatch.setattr(predict, "_model", model)
    return model


def test_score_window_normal_returns_not_anomaly(trained_test_model):
    window = make_window(avg_voltage=230.0, avg_current=10.0, power_variance=1.0)
    result = predict.score_window(window)
    assert result is not None
    is_anomaly, _score = result
    assert is_anomaly is False


def test_score_window_voltage_sag_returns_anomaly(trained_test_model):
    # Matches Phase 2's simulator voltage_sag pattern: ~150V instead of ~230V.
    window = make_window(avg_voltage=150.0, avg_current=10.0, power_variance=1.0)
    result = predict.score_window(window)
    assert result is not None
    is_anomaly, _score = result
    assert is_anomaly is True


def test_anomalous_ingestion_creates_open_anomaly(
    client, db_session, seed_users_and_meters, trained_test_model
):
    meter_a = seed_users_and_meters["meter_a"]
    window_start = floor_to_window(datetime.now(timezone.utc) - timedelta(minutes=30))
    for offset_minutes in (1, 5, 9):
        ts = window_start + timedelta(minutes=offset_minutes)
        resp = client.post(
            "/api/readings",
            json=_reading_body("MTR-A", voltage=150.0, current=10.0, ts=ts),
            headers={"x-device-key": "KEY-A"},
        )
        assert resp.status_code == 201

    window = (
        db_session.query(ReadingWindow)
        .filter(
            ReadingWindow.meter_id == meter_a.id,
            ReadingWindow.window_start == window_start,
        )
        .first()
    )
    assert window is not None
    assert window.is_anomaly is True
    assert window.scored_at is not None

    anomaly = (
        db_session.query(Anomaly).filter(Anomaly.reading_window_id == window.id).first()
    )
    assert anomaly is not None
    assert anomaly.status == AnomalyStatus.open
    assert anomaly.meter_id == meter_a.id


def _create_anomalous_window(client, meter_code: str, device_key: str) -> datetime:
    window_start = floor_to_window(datetime.now(timezone.utc) - timedelta(minutes=30))
    for offset_minutes in (1, 5, 9):
        ts = window_start + timedelta(minutes=offset_minutes)
        resp = client.post(
            "/api/readings",
            json=_reading_body(meter_code, voltage=150.0, current=10.0, ts=ts),
            headers={"x-device-key": device_key},
        )
        assert resp.status_code == 201
    return window_start


def test_list_anomalies_admin_only(client, db_session, seed_users_and_meters, trained_test_model):
    meter_a = seed_users_and_meters["meter_a"]
    _create_anomalous_window(client, "MTR-A", "KEY-A")

    consumer_resp = client.get("/api/anomalies", headers=auth_headers(seed_users_and_meters["token_a"]))
    assert consumer_resp.status_code == 403

    admin_resp = client.get("/api/anomalies", headers=auth_headers(seed_users_and_meters["token_admin"]))
    assert admin_resp.status_code == 200
    body = admin_resp.json()
    assert len(body) == 1
    assert body[0]["meter_id"] == str(meter_a.id)
    assert body[0]["status"] == "open"


def test_patch_anomaly_status_admin_only(client, seed_users_and_meters, trained_test_model):
    _create_anomalous_window(client, "MTR-A", "KEY-A")
    admin_token = seed_users_and_meters["token_admin"]
    anomaly_id = client.get("/api/anomalies", headers=auth_headers(admin_token)).json()[0]["id"]

    consumer_resp = client.patch(
        f"/api/anomalies/{anomaly_id}/status",
        json={"status": "confirmed_theft", "notes": "should be rejected"},
        headers=auth_headers(seed_users_and_meters["token_a"]),
    )
    assert consumer_resp.status_code == 403

    admin_resp = client.patch(
        f"/api/anomalies/{anomaly_id}/status",
        json={"status": "confirmed_theft", "notes": "confirmed via meter inspection"},
        headers=auth_headers(admin_token),
    )
    assert admin_resp.status_code == 200
    body = admin_resp.json()
    assert body["status"] == "confirmed_theft"
    assert body["notes"] == "confirmed via meter inspection"
    assert body["reviewed_by"] == str(seed_users_and_meters["admin"].id)
    assert body["reviewed_at"] is not None


def test_missing_model_does_not_break_ingestion(client, db_session, seed_users_and_meters, monkeypatch):
    # Simulate a fresh clone that hasn't run `python -m app.ml.train` yet.
    monkeypatch.setattr(predict, "MODEL_PATH", predict.MODEL_PATH.parent / "does-not-exist.pkl")
    predict.load_model()
    assert predict._model is None

    meter_a = seed_users_and_meters["meter_a"]
    window_start = floor_to_window(datetime.now(timezone.utc) - timedelta(minutes=30))
    resp = client.post(
        "/api/readings",
        json=_reading_body("MTR-A", voltage=230.0, current=10.0, ts=window_start + timedelta(minutes=1)),
        headers={"x-device-key": "KEY-A"},
    )
    assert resp.status_code == 201

    window = (
        db_session.query(ReadingWindow)
        .filter(
            ReadingWindow.meter_id == meter_a.id,
            ReadingWindow.window_start == window_start,
        )
        .first()
    )
    assert window is not None
    assert window.scored_at is None
    assert window.is_anomaly is False
    assert window.anomaly_score is None
