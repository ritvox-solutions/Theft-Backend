import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.anomaly import Anomaly, AnomalyStatus

# Valid PATCH targets — "open" is a starting state, not something you PATCH back to.
UPDATABLE_STATUSES = {AnomalyStatus.reviewed, AnomalyStatus.confirmed_theft, AnomalyStatus.false_positive}


class ReadingWindowSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    window_start: datetime
    window_end: datetime
    avg_voltage: float
    avg_current: float
    avg_power: float


class AnomalyOut(BaseModel):
    id: uuid.UUID
    reading_window_id: uuid.UUID
    meter_id: uuid.UUID
    anomaly_score: float
    status: AnomalyStatus
    detected_at: datetime
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    notes: str | None
    reading_window: ReadingWindowSummary

    # Denormalized onto the alert row so the admin table doesn't need a
    # separate meters/users lookup per row — both relationships already
    # exist on the Anomaly/Meter models, this just surfaces them.
    meter_code: str
    consumer_name: str

    @classmethod
    def from_orm_anomaly(cls, anomaly: Anomaly) -> "AnomalyOut":
        return cls(
            id=anomaly.id,
            reading_window_id=anomaly.reading_window_id,
            meter_id=anomaly.meter_id,
            anomaly_score=anomaly.anomaly_score,
            status=anomaly.status,
            detected_at=anomaly.detected_at,
            reviewed_by=anomaly.reviewed_by,
            reviewed_at=anomaly.reviewed_at,
            notes=anomaly.notes,
            reading_window=ReadingWindowSummary.model_validate(anomaly.reading_window),
            meter_code=anomaly.meter.meter_code,
            consumer_name=anomaly.meter.user.name,
        )


class AnomalyStatusUpdate(BaseModel):
    status: AnomalyStatus
    notes: str | None = None
