import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.bill import Bill, BillStatus
from app.models.meter import Meter, MeterStatus
from app.models.reading_window import ReadingWindow
from app.models.tariff_config import TariffConfig
from app.services.pdf import generate_bill_pdf

DEFAULT_SLABS = [
    {"upto_kwh": 100, "rate": 5.0},
    {"upto_kwh": 300, "rate": 7.5},
    {"upto_kwh": None, "rate": 10.0},
]
DEFAULT_FIXED_CHARGE = 50.0


def compute_bill_amount(units_kwh: float, tariff: TariffConfig) -> float:
    """Progressive slab billing: units within each slab are charged at that
    slab's rate, not the whole amount at the top slab reached. `slabs` is a
    list of {"upto_kwh": <cumulative upper bound, or null for the top/open
    slab>, "rate": <per-kWh rate>}, ordered ascending. fixed_charge is added
    once regardless of usage.
    """
    remaining = float(units_kwh)
    lower_bound = 0.0
    total = 0.0

    for slab in tariff.slabs:
        upto = slab["upto_kwh"]
        rate = float(slab["rate"])
        slab_width = remaining if upto is None else (upto - lower_bound)
        slab_units = max(0.0, min(remaining, slab_width))

        total += slab_units * rate
        remaining -= slab_units
        lower_bound = lower_bound if upto is None else upto

        if remaining <= 0:
            break

    return round(total + float(tariff.fixed_charge), 2)


def get_effective_tariff(db: Session, as_of: date) -> TariffConfig | None:
    """The tariff in effect on a given date — the most recent version whose
    effective_from is on or before `as_of`, not necessarily the latest overall
    (a bill for a past cycle uses what was actually in effect then)."""
    return (
        db.query(TariffConfig)
        .filter(TariffConfig.effective_from <= as_of)
        .order_by(TariffConfig.effective_from.desc(), TariffConfig.created_at.desc())
        .first()
    )


def _cycle_datetime_range(cycle_start: date, cycle_end: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(cycle_start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(cycle_end, time.min, tzinfo=timezone.utc) + timedelta(days=1)
    return start_dt, end_dt


def generate_bill_for_cycle(
    db: Session, meter_id: uuid.UUID, cycle_start: date, cycle_end: date
) -> tuple[Bill | None, str | None]:
    """Returns (bill, None) on success, or (None, error_message) — including
    the "already exists" case, which relies on the DB's unique constraint on
    (meter_id, cycle_start, cycle_end) rather than a check-first query."""
    tariff = get_effective_tariff(db, cycle_start)
    if tariff is None:
        return None, "No tariff configuration is effective as of the cycle start date."

    start_dt, end_dt = _cycle_datetime_range(cycle_start, cycle_end)
    units_kwh = (
        db.query(func.coalesce(func.sum(ReadingWindow.energy_kwh), 0))
        .filter(
            ReadingWindow.meter_id == meter_id,
            ReadingWindow.window_start >= start_dt,
            ReadingWindow.window_start < end_dt,
        )
        .scalar()
    )
    units_kwh = float(units_kwh)
    amount = compute_bill_amount(units_kwh, tariff)

    bill = Bill(
        meter_id=meter_id,
        cycle_start=cycle_start,
        cycle_end=cycle_end,
        units_consumed_kwh=units_kwh,
        amount=amount,
        status=BillStatus.generated,
        has_no_readings=units_kwh <= 0,
    )
    db.add(bill)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return None, "A bill already exists for this meter and cycle."

    meter = db.get(Meter, meter_id)
    pdf_path = generate_bill_pdf(bill, meter, meter.user.name, tariff)
    bill.pdf_path = pdf_path

    db.commit()
    db.refresh(bill)
    return bill, None


def generate_bills_for_all_active_meters(
    db: Session, cycle_start: date, cycle_end: date
) -> dict:
    """Loops active meters, generating a bill for each — skips (not errors)
    any meter that already has a bill for this cycle."""
    meters = db.query(Meter).filter(Meter.status == MeterStatus.active).all()
    generated, skipped = [], []
    for meter in meters:
        bill, error = generate_bill_for_cycle(db, meter.id, cycle_start, cycle_end)
        if bill is not None:
            generated.append(bill)
        else:
            skipped.append({"meter_id": str(meter.id), "meter_code": meter.meter_code, "reason": error})
    return {"generated": generated, "skipped": skipped}
