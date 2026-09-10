import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.meter import Meter
from app.models.reading import Reading
from app.models.user import User
from app.schemas.reading import (
    ReadingCreatedOut,
    ReadingIn,
    ReadingOut,
    RelayCommandOut,
)
from app.services.aggregation import run_aggregation_task
from app.services.auth import get_current_user
from app.services.device_auth import get_meter_by_device_key

router = APIRouter(prefix="/api/readings", tags=["readings"])


@router.post("", response_model=ReadingCreatedOut, status_code=status.HTTP_201_CREATED)
def create_reading(
    payload: ReadingIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    meter: Meter = Depends(get_meter_by_device_key),
):
    # Defense in depth: the device key alone resolves the meter; the body's
    # meter_id must also match it, so a leaked key for meter A can't be used
    # to post data under meter B's identity just by changing the body.
    if payload.meter_id != meter.meter_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="meter_id does not match the device key's meter",
        )

    from app.config import CURRENT_NOISE_DEADBAND, THEFT_CURRENT_THRESHOLD

    # Clean sensor ambient noise and calibrate currents
    volt = payload.voltage if payload.voltage >= 30.0 else 0.0
    curr = payload.current if payload.current >= CURRENT_NOISE_DEADBAND else 0.0
    source_curr = payload.source_current if payload.source_current is not None else curr
    if source_curr < CURRENT_NOISE_DEADBAND:
        source_curr = 0.0

    delta_curr = round(max(0.0, source_curr - curr), 3)
    theft_det = bool(payload.theft_detected) if payload.theft_detected is not None else False
    if delta_curr >= THEFT_CURRENT_THRESHOLD:
        theft_det = True

    reading = Reading(
        meter_id=meter.id,
        voltage=volt,
        current=curr,
        source_current=source_curr,
        delta_current=delta_curr,
        power=round(volt * curr, 2),
        recorded_at=payload.timestamp,
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)

    try:
        from app.services.ws_manager import ws_manager
        ws_manager.broadcast_threadsafe(
            {
                "type": "reading",
                "meter_id": str(meter.id),
                "meter_code": meter.meter_code,
                "reading": {
                    "id": str(reading.id),
                    "meter_id": str(meter.id),
                    "voltage": float(reading.voltage),
                    "current": float(reading.current),
                    "source_current": float(reading.source_current or 0.0),
                    "delta_current": float(reading.delta_current or 0.0),
                    "theft_detected": theft_det,
                    "power": float(reading.power),
                    "recorded_at": reading.recorded_at.isoformat(),
                    "created_at": reading.created_at.isoformat() if reading.created_at else reading.recorded_at.isoformat(),
                },
                "theft_detected": theft_det,
                "relay_state": meter.relay_state.value if hasattr(meter.relay_state, "value") else str(meter.relay_state),
            },
            target_meter_id=meter.id,
        )
    except Exception:
        pass

    # If hardware differential theft is detected, register anomaly immediately
    if theft_det and delta_curr >= THEFT_CURRENT_THRESHOLD:
        from datetime import timedelta, timezone
        from app.models.reading_window import ReadingWindow
        from app.services.aggregation import floor_to_window, WINDOW_MINUTES
        from app.services.anomalies import create_anomaly_if_missing

        window_start = floor_to_window(payload.timestamp)
        window = (
            db.query(ReadingWindow)
            .filter(
                ReadingWindow.meter_id == meter.id,
                ReadingWindow.window_start == window_start,
            )
            .first()
        )
        if window is None:
            window = ReadingWindow(
                meter_id=meter.id,
                window_start=window_start,
                window_end=window_start + timedelta(minutes=WINDOW_MINUTES),
                avg_voltage=volt,
                avg_current=curr,
                avg_power=reading.power,
                power_variance=0.0,
                reading_count=1,
                energy_kwh=(reading.power * (WINDOW_MINUTES / 60)) / 1000,
                is_anomaly=True,
                anomaly_score=0.99,
                scored_at=datetime.now(timezone.utc),
            )
            db.add(window)
            db.flush()
        else:
            window.is_anomaly = True
            window.anomaly_score = 0.99
            window.scored_at = datetime.now(timezone.utc)
            db.flush()

        anomaly = create_anomaly_if_missing(
            db,
            window,
            0.99,
            notes=f"Physical line tap detected: {delta_curr:.3f}A bypassing junction box (Source={source_curr:.3f}A, Metered={curr:.3f}A).",
        )
        if anomaly:
            try:
                from app.services.ws_manager import ws_manager
                ws_manager.broadcast_threadsafe(
                    {
                        "type": "anomaly",
                        "meter_id": str(meter.id),
                        "meter_code": meter.meter_code,
                        "anomaly": {
                            "id": str(anomaly.id),
                            "meter_id": str(meter.id),
                            "meter_code": meter.meter_code,
                            "anomaly_score": float(anomaly.anomaly_score),
                            "status": anomaly.status.value if hasattr(anomaly.status, "value") else str(anomaly.status),
                            "detected_at": anomaly.detected_at.isoformat(),
                            "notes": anomaly.notes,
                        },
                    }
                )
            except Exception:
                pass
        db.commit()

    background_tasks.add_task(run_aggregation_task, meter.id)

    return ReadingCreatedOut(id=reading.id, relay_command=meter.relay_state)


@router.get("/relay", response_model=RelayCommandOut)
def get_relay_command(meter: Meter = Depends(get_meter_by_device_key)):
    """Device-key authenticated: lets a meter fetch its desired relay state on
    boot (before it has a reading to POST) or poll it out of band. The same
    value rides on every POST /api/readings response as `relay_command`.

    Declared before GET /{meter_id} so "relay" isn't parsed as a meter UUID.
    """
    return RelayCommandOut(relay_command=meter.relay_state)


@router.get("/{meter_id}", response_model=list[ReadingOut])
def list_readings(
    meter_id: uuid.UUID,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meter = db.get(Meter, meter_id)
    if meter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meter not found")
    if current_user.role.value != "admin" and meter.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your meter")

    query = db.query(Reading).filter(Reading.meter_id == meter_id)
    if start is not None:
        query = query.filter(Reading.recorded_at >= start)
    if end is not None:
        query = query.filter(Reading.recorded_at <= end)
    else:
        # Prevent any future-dated entries from blocking live readings
        from datetime import timedelta, timezone
        query = query.filter(Reading.recorded_at <= datetime.now(timezone.utc) + timedelta(minutes=1))
    query = query.order_by(Reading.recorded_at.desc()).limit(limit)
    return query.all()
