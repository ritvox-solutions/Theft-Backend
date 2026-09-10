import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

import calendar
from datetime import date, datetime, timezone

from sqlalchemy import func

from app.database import get_db
from app.models.bill import Bill, BillStatus
from app.models.meter import Meter
from app.models.reading import Reading
from app.models.reading_window import ReadingWindow
from app.models.tariff_config import TariffConfig
from app.models.user import User
from app.schemas.billing import BillOut, BillStatusUpdate, CurrentCycleEstimate
from app.services.aggregation import floor_to_window
from app.services.auth import get_current_user, require_admin
from app.services.billing import (
    DEFAULT_FIXED_CHARGE,
    DEFAULT_SLABS,
    _cycle_datetime_range,
    compute_bill_amount,
    get_effective_tariff,
)

router = APIRouter(prefix="/api/bills", tags=["bills"])


@router.get("", response_model=list[BillOut])
def list_all_bills(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    bills = db.query(Bill).order_by(Bill.generated_at.desc()).all()
    return [BillOut.from_orm_bill(b) for b in bills]


@router.get("/{meter_id}/estimate", response_model=CurrentCycleEstimate)
def get_current_estimate(
    meter_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Computes live running energy usage and estimated bill for the current billing cycle."""
    meter = db.get(Meter, meter_id)
    if meter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meter not found")
    if current_user.role.value != "admin" and meter.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your meter")

    today = date.today()
    cycle_start = today.replace(day=1)
    _, last_day = calendar.monthrange(today.year, today.month)
    cycle_end = today.replace(day=last_day)

    tariff = get_effective_tariff(db, cycle_start)
    if tariff is None:
        tariff = TariffConfig(
            effective_from=cycle_start,
            slabs=DEFAULT_SLABS,
            fixed_charge=DEFAULT_FIXED_CHARGE,
            created_by=meter.user_id,
        )

    start_dt, end_dt = _cycle_datetime_range(cycle_start, cycle_end)

    # Demo Mode: Calculate accumulated energy directly from real-time readings
    # Each reading represents a ~10 second slice. DEMO_SPEEDUP = 100.0 accelerates
    # energy accumulation so units and money visibly tick up live during a short presentation.
    DEMO_SPEEDUP = 100.0

    readings = (
        db.query(Reading.power)
        .filter(
            Reading.meter_id == meter_id,
            Reading.recorded_at >= start_dt,
            Reading.recorded_at < end_dt,
        )
        .all()
    )

    total_power_sum = sum(float(r[0]) for r in readings if r[0] and float(r[0]) > 0)
    total_units_kwh = round((total_power_sum * 10.0 / 3600000.0) * DEMO_SPEEDUP, 3)

    total_amount = compute_bill_amount(total_units_kwh, tariff)
    fixed_charge = float(tariff.fixed_charge)
    energy_charge = round(max(0.0, total_amount - fixed_charge), 2)

    return CurrentCycleEstimate(
        meter_id=meter.id,
        cycle_start=cycle_start,
        cycle_end=cycle_end,
        units_consumed_kwh=total_units_kwh,
        fixed_charge=fixed_charge,
        energy_charge=energy_charge,
        estimated_amount=total_amount,
        currency="INR",
    )


@router.get("/{meter_id}", response_model=list[BillOut])
def list_bills_for_meter(
    meter_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meter = db.get(Meter, meter_id)
    if meter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meter not found")
    if current_user.role.value != "admin" and meter.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your meter")

    bills = (
        db.query(Bill)
        .filter(Bill.meter_id == meter_id)
        .order_by(Bill.cycle_start.desc())
        .all()
    )
    return [BillOut.from_orm_bill(b) for b in bills]


@router.post("/{bill_id}/pay", response_model=BillOut)
def pay_bill(
    bill_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Allows a consumer or admin to pay their electricity bill online."""
    bill = db.get(Bill, bill_id)
    if bill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bill not found")

    meter = db.get(Meter, bill.meter_id)
    if current_user.role.value != "admin" and meter.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your bill")

    bill.status = BillStatus.paid
    db.commit()
    db.refresh(bill)
    return BillOut.from_orm_bill(bill)


@router.patch("/{bill_id}/status", response_model=BillOut)
def update_bill_status(
    bill_id: uuid.UUID,
    payload: BillStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bill = db.get(Bill, bill_id)
    if bill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bill not found")

    meter = db.get(Meter, bill.meter_id)
    if current_user.role.value != "admin" and meter.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    bill.status = payload.status
    db.commit()
    db.refresh(bill)
    return BillOut.from_orm_bill(bill)


@router.get("/{bill_id}/pdf")
def download_bill_pdf(
    bill_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    bill = db.get(Bill, bill_id)
    if bill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bill not found")

    meter = db.get(Meter, bill.meter_id)
    if current_user.role.value != "admin" and meter.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your bill")

    if not bill.pdf_path or not os.path.exists(bill.pdf_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF not found")

    filename = f"{meter.meter_code}-{bill.cycle_start}.pdf"
    return FileResponse(bill.pdf_path, media_type="application/pdf", filename=filename)
