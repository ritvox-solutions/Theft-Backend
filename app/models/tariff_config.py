import uuid
from datetime import date as date_type
from datetime import datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TariffConfig(Base):
    __tablename__ = "tariff_config"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    effective_from: Mapped[date_type] = mapped_column(Date, nullable=False)
    slabs: Mapped[list] = mapped_column(JSONB, nullable=False)
    fixed_charge: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # Breaks ties when two versions share the same effective_from (e.g. two
    # versions submitted the same day) — "most recent" needs a real ordering.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    creator: Mapped["User"] = relationship()
