import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AnomalyStatus(str, enum.Enum):
    open = "open"
    reviewed = "reviewed"
    confirmed_theft = "confirmed_theft"
    false_positive = "false_positive"


class Anomaly(Base):
    __tablename__ = "anomalies"
    __table_args__ = (Index("ix_anomalies_status_detected_at", "status", "detected_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    reading_window_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reading_windows.id"), nullable=False
    )
    meter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meters.id"), nullable=False
    )
    anomaly_score: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    status: Mapped[AnomalyStatus] = mapped_column(
        Enum(AnomalyStatus, name="anomaly_status"), nullable=False, default=AnomalyStatus.open
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    reading_window: Mapped["ReadingWindow"] = relationship(back_populates="anomalies")
    meter: Mapped["Meter"] = relationship()
    reviewer: Mapped["User | None"] = relationship(foreign_keys=[reviewed_by])
