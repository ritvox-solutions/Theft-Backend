from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.anomaly import Anomaly, AnomalyStatus
from app.models.reading_window import ReadingWindow
from app.services.notifications import notify_admins_of_anomaly


def create_anomaly_if_missing(
    db: Session, window: ReadingWindow, anomaly_score: float, notes: str | None = None
) -> Anomaly | None:
    """Creates an `anomalies` row for a flagged window, unless one already
    exists for this reading_window_id — a window is only scored once in the
    normal flow, but this guards against a future re-scoring path (e.g. a
    retrain followed by re-running detection) creating duplicates."""
    existing = (
        db.query(Anomaly).filter(Anomaly.reading_window_id == window.id).first()
    )
    if existing is not None:
        return None

    anomaly = Anomaly(
        reading_window_id=window.id,
        meter_id=window.meter_id,
        anomaly_score=anomaly_score,
        status=AnomalyStatus.open,
        detected_at=datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(anomaly)
    notify_admins_of_anomaly(db, anomaly)  # best-effort; never raises, see notifications.py
    return anomaly
