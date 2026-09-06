import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ReadingWindow(Base):
    __tablename__ = "reading_windows"
    __table_args__ = (Index("ix_reading_windows_meter_id_window_start", "meter_id", "window_start"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    meter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meters.id"), nullable=False
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    avg_voltage: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    avg_current: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    avg_power: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    power_variance: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    reading_count: Mapped[int] = mapped_column(Integer, nullable=False)
    energy_kwh: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    meter: Mapped["Meter"] = relationship(back_populates="reading_windows")
    anomalies: Mapped[list["Anomaly"]] = relationship(back_populates="reading_window")
