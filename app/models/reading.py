import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Reading(Base):
    __tablename__ = "readings"
    __table_args__ = (Index("ix_readings_meter_id_recorded_at", "meter_id", "recorded_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    meter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meters.id"), nullable=False
    )
    voltage: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    current: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    source_current: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    delta_current: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    power: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    frequency: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    power_factor: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    meter: Mapped["Meter"] = relationship(back_populates="readings")

    @property
    def theft_detected(self) -> bool:
        from app.config import THEFT_CURRENT_THRESHOLD
        return bool(self.delta_current is not None and float(self.delta_current) >= THEFT_CURRENT_THRESHOLD)

