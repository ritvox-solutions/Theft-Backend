from datetime import datetime, timedelta, timezone

from app.models.reading_window import ReadingWindow
from app.services.aggregation import floor_to_window


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _reading_body(meter_code: str, voltage: float = 231.4, current: float = 4.2, ts=None) -> dict:
    ts = ts or datetime.now(timezone.utc)
    return {
        "meter_id": meter_code,
        "voltage": voltage,
        "current": current,
        "timestamp": ts.isoformat(),
    }


def test_post_reading_with_valid_device_key_succeeds(client, seed_users_and_meters):
    resp = client.post(
        "/api/readings",
        json=_reading_body("MTR-A"),
        headers={"x-device-key": "KEY-A"},
    )
    assert resp.status_code == 201
    assert "id" in resp.json()


def test_post_reading_with_wrong_device_key_returns_401(client, seed_users_and_meters):
    resp = client.post(
        "/api/readings",
        json=_reading_body("MTR-A"),
        headers={"x-device-key": "not-a-real-key"},
    )
    assert resp.status_code == 401


def test_post_reading_with_missing_device_key_returns_401(client, seed_users_and_meters):
    resp = client.post("/api/readings", json=_reading_body("MTR-A"))
    assert resp.status_code in (401, 422)  # 422 if FastAPI rejects the missing required header


def test_post_reading_with_mismatched_meter_id_is_rejected(client, seed_users_and_meters):
    # KEY-A resolves to meter MTR-A, but the body claims to be MTR-B —
    # a leaked/reused key for one meter must not be able to post as another.
    resp = client.post(
        "/api/readings",
        json=_reading_body("MTR-B"),
        headers={"x-device-key": "KEY-A"},
    )
    assert resp.status_code == 400


def test_post_reading_for_inactive_meter_returns_403(client, db_session, seed_users_and_meters):
    from app.models.meter import Meter, MeterStatus

    meter_a = seed_users_and_meters["meter_a"]
    db_session.query(Meter).filter(Meter.id == meter_a.id).update({"status": MeterStatus.inactive})
    db_session.commit()

    resp = client.post(
        "/api/readings",
        json=_reading_body("MTR-A"),
        headers={"x-device-key": "KEY-A"},
    )
    assert resp.status_code == 403


def test_get_readings_as_owner_returns_data(client, seed_users_and_meters):
    client.post("/api/readings", json=_reading_body("MTR-A"), headers={"x-device-key": "KEY-A"})

    meter_a_id = seed_users_and_meters["meter_a"].id
    token = seed_users_and_meters["token_a"]
    resp = client.get(f"/api/readings/{meter_a_id}", headers=auth_headers(token))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["meter_id"] == str(meter_a_id)


def test_get_readings_as_other_consumer_returns_403(client, seed_users_and_meters):
    client.post("/api/readings", json=_reading_body("MTR-A"), headers={"x-device-key": "KEY-A"})

    meter_a_id = seed_users_and_meters["meter_a"].id
    token_b = seed_users_and_meters["token_b"]
    resp = client.get(f"/api/readings/{meter_a_id}", headers=auth_headers(token_b))
    assert resp.status_code == 403


def test_readings_spanning_a_window_boundary_produce_a_reading_window(
    client, db_session, seed_users_and_meters
):
    meter_a = seed_users_and_meters["meter_a"]

    # Post several readings whose recorded_at sits in a window that is
    # already closed relative to "now" (30 minutes ago) — this makes the
    # window aggregate immediately via the post-request background task,
    # instead of requiring a real 15-minute wait.
    window_start = floor_to_window(datetime.now(timezone.utc) - timedelta(minutes=30))
    for offset_minutes in (1, 5, 9):
        ts = window_start + timedelta(minutes=offset_minutes)
        resp = client.post(
            "/api/readings",
            json=_reading_body("MTR-A", voltage=230.0, current=10.0, ts=ts),
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
    assert window.reading_count == 3
    assert window.is_anomaly is False
    assert window.anomaly_score is None
    # 230V * 10A = 2300W, over a 15-minute window -> ~0.575 kWh; generous bounds
    # since this only needs to be "plausible", not exact.
    assert 0 < float(window.energy_kwh) < 2
