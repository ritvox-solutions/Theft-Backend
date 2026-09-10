import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.bill import Bill, BillStatus


class SlabIn(BaseModel):
    upto_kwh: float | None
    rate: float


class TariffConfigIn(BaseModel):
    slabs: list[SlabIn]
    fixed_charge: float
    effective_from: date | None = None  # defaults to today if omitted


class TariffConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    effective_from: date
    slabs: list[dict]
    fixed_charge: float
    created_by: uuid.UUID


class GenerateBillRequest(BaseModel):
    meter_id: uuid.UUID
    cycle_start: date
    cycle_end: date


class GenerateAllRequest(BaseModel):
    cycle_start: date
    cycle_end: date


class BillStatusUpdate(BaseModel):
    status: BillStatus


class CurrentCycleEstimate(BaseModel):
    meter_id: uuid.UUID
    cycle_start: date
    cycle_end: date
    units_consumed_kwh: float
    fixed_charge: float
    energy_charge: float
    estimated_amount: float
    currency: str = "INR"


class BillOut(BaseModel):
    id: uuid.UUID
    meter_id: uuid.UUID
    meter_code: str
    consumer_name: str
    cycle_start: date
    cycle_end: date
    units_consumed_kwh: float
    amount: float
    status: BillStatus
    pdf_path: str | None
    has_no_readings: bool
    generated_at: datetime

    @classmethod
    def from_orm_bill(cls, bill: Bill) -> "BillOut":
        return cls(
            id=bill.id,
            meter_id=bill.meter_id,
            meter_code=bill.meter.meter_code,
            consumer_name=bill.meter.user.name,
            cycle_start=bill.cycle_start,
            cycle_end=bill.cycle_end,
            units_consumed_kwh=bill.units_consumed_kwh,
            amount=bill.amount,
            status=bill.status,
            pdf_path=bill.pdf_path,
            has_no_readings=bill.has_no_readings,
            generated_at=bill.generated_at,
        )
