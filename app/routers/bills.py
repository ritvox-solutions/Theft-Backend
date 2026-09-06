import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.bill import Bill
from app.models.meter import Meter
from app.models.user import User
from app.schemas.billing import BillOut, BillStatusUpdate
from app.services.auth import get_current_user, require_admin

router = APIRouter(prefix="/api/bills", tags=["bills"])


@router.get("", response_model=list[BillOut])
def list_all_bills(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    bills = db.query(Bill).order_by(Bill.generated_at.desc()).all()
    return [BillOut.from_orm_bill(b) for b in bills]


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


@router.patch("/{bill_id}/status", response_model=BillOut)
def update_bill_status(
    bill_id: uuid.UUID,
    payload: BillStatusUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    bill = db.get(Bill, bill_id)
    if bill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bill not found")
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
