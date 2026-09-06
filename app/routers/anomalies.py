import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.anomaly import Anomaly, AnomalyStatus
from app.models.user import User
from app.schemas.anomaly import UPDATABLE_STATUSES, AnomalyOut, AnomalyStatusUpdate
from app.services.auth import require_admin

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


@router.get("", response_model=list[AnomalyOut])
def list_anomalies(
    status_filter: AnomalyStatus | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    query = db.query(Anomaly)
    if status_filter is not None:
        query = query.filter(Anomaly.status == status_filter)
    anomalies = query.order_by(Anomaly.detected_at.desc()).all()
    return [AnomalyOut.from_orm_anomaly(a) for a in anomalies]


@router.patch("/{anomaly_id}/status", response_model=AnomalyOut)
def update_anomaly_status(
    anomaly_id: uuid.UUID,
    payload: AnomalyStatusUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    anomaly = db.get(Anomaly, anomaly_id)
    if anomaly is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anomaly not found")
    if payload.status not in UPDATABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of {sorted(s.value for s in UPDATABLE_STATUSES)}",
        )

    anomaly.status = payload.status
    if payload.notes is not None:
        anomaly.notes = payload.notes
    anomaly.reviewed_by = admin.id
    anomaly.reviewed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(anomaly)
    return AnomalyOut.from_orm_anomaly(anomaly)
