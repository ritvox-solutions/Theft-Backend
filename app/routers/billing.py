from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tariff_config import TariffConfig
from app.models.user import User
from app.schemas.billing import (
    BillOut,
    GenerateAllRequest,
    GenerateBillRequest,
    TariffConfigIn,
    TariffConfigOut,
)
from app.services.auth import require_admin
from app.services.billing import (
    DEFAULT_FIXED_CHARGE,
    DEFAULT_SLABS,
    generate_bill_for_cycle,
    generate_bills_for_all_active_meters,
)

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/tariff", response_model=TariffConfigOut)
def get_current_tariff(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    tariff = (
        db.query(TariffConfig)
        .order_by(TariffConfig.effective_from.desc(), TariffConfig.created_at.desc())
        .first()
    )
    if tariff is None:
        tariff = TariffConfig(
            effective_from=date.today(),
            slabs=DEFAULT_SLABS,
            fixed_charge=DEFAULT_FIXED_CHARGE,
            created_by=admin.id,
        )
        db.add(tariff)
        db.commit()
        db.refresh(tariff)
    return tariff


@router.put("/tariff", response_model=TariffConfigOut)
def create_tariff_version(
    payload: TariffConfigIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # Always inserts a new row — never mutates an existing one, so historical
    # bills stay explainable against the tariff that was actually in effect.
    tariff = TariffConfig(
        effective_from=payload.effective_from or date.today(),
        slabs=[s.model_dump() for s in payload.slabs],
        fixed_charge=payload.fixed_charge,
        created_by=admin.id,
    )
    db.add(tariff)
    db.commit()
    db.refresh(tariff)
    return tariff


@router.post("/generate")
def generate_bill(
    payload: GenerateBillRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    bill, error = generate_bill_for_cycle(db, payload.meter_id, payload.cycle_start, payload.cycle_end)
    if bill is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error)
    return BillOut.from_orm_bill(bill)


@router.post("/generate-all")
def generate_all(
    payload: GenerateAllRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = generate_bills_for_all_active_meters(db, payload.cycle_start, payload.cycle_end)
    return {
        "generated": [BillOut.from_orm_bill(b) for b in result["generated"]],
        "skipped": result["skipped"],
    }
