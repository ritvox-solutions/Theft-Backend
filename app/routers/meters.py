import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.meter import Meter
from app.models.user import User
from app.schemas.meter import MeterCreate, MeterOut, MeterUpdate, RelayUpdate
from app.services.access import scope_to_owner
from app.services.auth import get_current_user, require_admin

router = APIRouter(prefix="/api/meters", tags=["meters"])


@router.get("", response_model=list[MeterOut])
def list_meters(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    query = scope_to_owner(db.query(Meter), Meter, current_user)
    return query.all()


@router.get("/{meter_id}", response_model=MeterOut)
def get_meter(
    meter_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meter = db.get(Meter, meter_id)
    if meter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meter not found")
    if current_user.role.value != "admin" and meter.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your meter")
    return meter


@router.post("", response_model=MeterOut, status_code=status.HTTP_201_CREATED)
def create_meter(
    payload: MeterCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    owner = db.get(User, payload.user_id)
    if owner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_id not found")

    meter = Meter(**payload.model_dump())
    db.add(meter)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="meter_code or device_key already in use",
        )
    db.refresh(meter)
    return meter


@router.put("/{meter_id}", response_model=MeterOut)
def update_meter(
    meter_id: uuid.UUID,
    payload: MeterUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    meter = db.get(Meter, meter_id)
    if meter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meter not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(meter, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="meter_code already in use"
        )
    db.refresh(meter)
    return meter


@router.patch("/{meter_id}/relay", response_model=MeterOut)
def set_relay(
    meter_id: uuid.UUID,
    payload: RelayUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Set the desired load-disconnect relay state. Independent of meter
    status — the meter keeps metering. The device applies this on its next
    reading POST (or GET /api/readings/relay)."""
    meter = db.get(Meter, meter_id)
    if meter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meter not found")
    meter.relay_state = payload.state
    meter.relay_updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(meter)
    return meter


@router.delete("/{meter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meter(
    meter_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    meter = db.get(Meter, meter_id)
    if meter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meter not found")
    db.delete(meter)
    db.commit()
