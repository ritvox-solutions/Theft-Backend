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

    reading = Reading(
        meter_id=meter.id,
        voltage=payload.voltage,
        current=payload.current,
        power=payload.voltage * payload.current,
        recorded_at=payload.timestamp,
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)

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
    query = query.order_by(Reading.recorded_at.desc()).limit(limit)
    return query.all()
