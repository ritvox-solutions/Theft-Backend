import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.meter import MeterStatus, RelayState


class MeterCreate(BaseModel):
    meter_code: str
    user_id: uuid.UUID
    device_key: str
    location_label: str | None = None
    status: MeterStatus = MeterStatus.active


class MeterUpdate(BaseModel):
    meter_code: str | None = None
    location_label: str | None = None
    status: MeterStatus | None = None


class RelayUpdate(BaseModel):
    state: RelayState


class MeterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    meter_code: str
    user_id: uuid.UUID
    device_key: str
    location_label: str | None
    status: MeterStatus
    relay_state: RelayState
    relay_updated_at: datetime | None
    created_at: datetime
