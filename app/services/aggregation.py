import uuid
from datetime import datetime, timedelta, timezone
from statistics import mean, pvariance

from sqlalchemy.orm import Session

from app.ml.predict import score_window
from app.models.reading import Reading
from app.models.reading_window import ReadingWindow
from app.services.anomalies import create_anomaly_if_missing

WINDOW_MINUTES = 15


def floor_to_window(dt: datetime, minutes: int = WINDOW_MINUTES) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    window_seconds = minutes * 60
    floored_epoch = (dt.timestamp() // window_seconds) * window_seconds
    return datetime.fromtimestamp(floored_epoch, tz=timezone.utc)


def aggregate_closed_windows(db: Session, meter_id: uuid.UUID) -> list[ReadingWindow]:
    """Rolls up readings whose 15-minute window has closed into reading_windows rows.

    Idempotent via upsert: a window that already has a reading_windows row gets
    its aggregates recomputed from the full current set of readings in that
    window rather than skipped — plain "skip if exists" would silently freeze
    the row after the first reading in a window (e.g. readings that arrive out
    of order, or backfilled data), since every ingested reading tries to close
    out its window as soon as it lands. This never creates a second row for the
    same (meter_id, window_start) — always the same row, recomputed in place.

    Every window touched here (new or recomputed) is (re-)scored via
    app.ml.predict.score_window — recomputed aggregates make any prior score
    stale, so upserts get rescored too. If no model is loaded, scoring is
    skipped entirely and is_anomaly/anomaly_score/scored_at are left as-is
    (NULL/False on a new row) rather than raising — ingestion must never break
    because ML isn't ready yet.
    """
    current_window_start = floor_to_window(datetime.now(timezone.utc))

    readings = (
        db.query(Reading)
        .filter(Reading.meter_id == meter_id, Reading.recorded_at < current_window_start)
        .all()
    )
    if not readings:
        return []

    buckets: dict[datetime, list[Reading]] = {}
    for reading in readings:
        window_start = floor_to_window(reading.recorded_at)
        buckets.setdefault(window_start, []).append(reading)

    touched: list[ReadingWindow] = []
    for window_start, group in buckets.items():
        voltages = [float(r.voltage) for r in group]
        currents = [float(r.current) for r in group]
        powers = [float(r.power) for r in group]

        avg_voltage = mean(voltages)
        avg_current = mean(currents)
        avg_power = mean(powers)
        power_variance = pvariance(powers) if len(powers) > 1 else 0.0
        duration_hours = WINDOW_MINUTES / 60
        energy_kwh = (avg_power * duration_hours) / 1000

        window = (
            db.query(ReadingWindow)
            .filter(
                ReadingWindow.meter_id == meter_id,
                ReadingWindow.window_start == window_start,
            )
            .first()
        )
        if window is None:
            window = ReadingWindow(
                meter_id=meter_id,
                window_start=window_start,
                window_end=window_start + timedelta(minutes=WINDOW_MINUTES),
                is_anomaly=False,
                anomaly_score=None,
                scored_at=None,
            )
            db.add(window)

        window.avg_voltage = avg_voltage
        window.avg_current = avg_current
        window.avg_power = avg_power
        window.power_variance = power_variance
        window.reading_count = len(group)
        window.energy_kwh = energy_kwh
        touched.append(window)

    db.flush()  # assigns .id to newly-created windows before scoring/anomaly creation

    for window in touched:
        # Idle / no-load state (power off, standby, or bench testing) is never an anomaly
        if window.avg_voltage < 30.0 or window.avg_current < 0.05:
            window.is_anomaly = False
            window.anomaly_score = 0.0
            window.scored_at = datetime.now(timezone.utc)
            continue

        result = score_window(window)
        if result is None:
            continue
        is_anomaly, anomaly_score = result
        window.is_anomaly = is_anomaly
        window.anomaly_score = anomaly_score
        window.scored_at = datetime.now(timezone.utc)
        if is_anomaly:
            create_anomaly_if_missing(db, window, anomaly_score)

    db.commit()
    return touched


def run_aggregation_task(meter_id: uuid.UUID) -> None:
    """Entry point for FastAPI BackgroundTasks — opens its own session so it
    doesn't depend on the request-scoped session's lifecycle."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        aggregate_closed_windows(db, meter_id)
    finally:
        db.close()
