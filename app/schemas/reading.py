import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.meter import RelayState


class ReadingIn(BaseModel):
    meter_id: str  # human-readable meter_code, cross-checked against the device key's meter
    voltage: float
    current: float
    timestamp: datetime


class ReadingCreatedOut(BaseModel):
    id: uuid.UUID
    # Desired relay state for this meter — the device applies it every cycle.
    relay_command: RelayState


class RelayCommandOut(BaseModel):
    relay_command: RelayState


class ReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    meter_id: uuid.UUID
    voltage: float
    current: float
    power: float
    frequency: float | None
    power_factor: float | None
    recorded_at: datetime
    created_at: datetime
