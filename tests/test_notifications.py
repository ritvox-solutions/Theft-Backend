from datetime import datetime, timedelta, timezone

from app.models.anomaly import Anomaly
from app.models.reading_window import ReadingWindow
from app.services import notifications
from app.services.anomalies import create_anomaly_if_missing


def _make_window(meter_id, is_anomaly: bool = True) -> ReadingWindow:
    now = datetime.now(timezone.utc)
    return ReadingWindow(
        meter_id=meter_id,
        window_start=now,
        window_end=now + timedelta(minutes=15),
        avg_voltage=150.0,
        avg_current=10.0,
        avg_power=1500.0,
        power_variance=1.0,
        reading_count=3,
        energy_kwh=0.375,
        is_anomaly=is_anomaly,
    )


def test_email_send_failure_does_not_block_anomaly_creation(
    db_session, seed_users_and_meters, monkeypatch
):
    monkeypatch.setattr(notifications, "RESEND_API_KEY", "fake-key-for-test")

    def raise_error(*args, **kwargs):
        raise Exception("simulated email provider outage")

    monkeypatch.setattr(notifications.urllib.request, "urlopen", raise_error)

    meter_a = seed_users_and_meters["meter_a"]
    window = _make_window(meter_a.id)
    db_session.add(window)
    db_session.flush()

    anomaly = create_anomaly_if_missing(db_session, window, anomaly_score=0.42)
    db_session.commit()

    assert anomaly is not None
    stored = db_session.query(Anomaly).filter(Anomaly.reading_window_id == window.id).first()
    assert stored is not None
    assert stored.status.value == "open"


def test_missing_api_key_skips_email_but_still_creates_anomaly(
    db_session, seed_users_and_meters, monkeypatch
):
    monkeypatch.setattr(notifications, "RESEND_API_KEY", None)

    meter_a = seed_users_and_meters["meter_a"]
    window = _make_window(meter_a.id)
    db_session.add(window)
    db_session.flush()

    anomaly = create_anomaly_if_missing(db_session, window, anomaly_score=0.42)
    db_session.commit()

    assert anomaly is not None
    stored = db_session.query(Anomaly).filter(Anomaly.reading_window_id == window.id).first()
    assert stored is not None
