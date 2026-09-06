import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class MeterStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"


class RelayState(str, enum.Enum):
    """Desired physical state of the meter's load-disconnect relay. Independent
    of `MeterStatus`: a meter can still be `active` (metering, reporting) while
    its relay is `disconnected` (load cut, e.g. after confirmed theft). The
    device applies this on every reading POST (returned as `relay_command`)."""

    connected = "connected"
    disconnected = "disconnected"


class Meter(Base):
    __tablename__ = "meters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    meter_code: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    device_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    location_label: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[MeterStatus] = mapped_column(
        Enum(MeterStatus, name="meter_status"), nullable=False, default=MeterStatus.active
    )
    relay_state: Mapped[RelayState] = mapped_column(
        Enum(RelayState, name="relay_state"),
        nullable=False,
        default=RelayState.connected,
        server_default=RelayState.connected.value,
    )
    relay_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="meters", foreign_keys=[user_id])
    readings: Mapped[list["Reading"]] = relationship(back_populates="meter")
    reading_windows: Mapped[list["ReadingWindow"]] = relationship(back_populates="meter")
    bills: Mapped[list["Bill"]] = relationship(back_populates="meter")
