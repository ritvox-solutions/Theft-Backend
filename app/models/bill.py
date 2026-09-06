import enum
import uuid
from datetime import date as date_type
from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BillStatus(str, enum.Enum):
    generated = "generated"
    viewed = "viewed"
    paid = "paid"


class Bill(Base):
    __tablename__ = "bills"
    __table_args__ = (
        UniqueConstraint("meter_id", "cycle_start", "cycle_end", name="uq_bills_meter_cycle"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    meter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meters.id"), nullable=False
    )
    cycle_start: Mapped[date_type] = mapped_column(Date, nullable=False)
    cycle_end: Mapped[date_type] = mapped_column(Date, nullable=False)
    units_consumed_kwh: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[BillStatus] = mapped_column(
        Enum(BillStatus, name="bill_status"), nullable=False, default=BillStatus.generated
    )
    pdf_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # True when the cycle had zero metered units — surfaced distinctly in the
    # UI so a fixed-charge-only bill reads as "meter reported no data" rather
    # than as an unexplained flat charge (App Flow doc §6).
    has_no_readings: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    meter: Mapped["Meter"] = relationship(back_populates="bills")
