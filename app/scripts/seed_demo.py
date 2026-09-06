"""Demo dataset for a live walkthrough — additive and separate from
`app/seed.py` and `app/scripts/seed_training_data.py`; never modifies either.

Prerequisites: `python -m app.seed` (creates the 5 consumer meters this script
uses). A trained `app/ml/model.pkl` is NOT required — this script guarantees
the anomalous meter ends up with an open alert even if scoring is unavailable
(see `_ensure_anomaly_flagged`), so it's safe to run before or after
`python -m app.ml.train`.

Run:
    python -m app.scripts.seed_demo

Re-runnable by design: each run first deletes any readings/reading_windows/
anomalies/bills it previously created for the 5 demo meters, then regenerates
them fresh, so it can be run right before a demo with no manual cleanup.
Deliberately does NOT touch users, meters, device keys, MTR-TRAIN, or tariff
history — only the per-meter usage/alert/bill data below.
"""

import random
from datetime import date, datetime, timedelta, timezone

from app.database import SessionLocal
from app.models.anomaly import Anomaly
from app.models.bill import Bill, BillStatus
from app.models.meter import Meter
from app.models.reading import Reading
from app.models.reading_window import ReadingWindow
from app.models.tariff_config import TariffConfig
from app.models.user import User, UserRole
from app.services.aggregation import aggregate_closed_windows
from app.services.anomalies import create_anomaly_if_missing
from app.services.billing import DEFAULT_FIXED_CHARGE, DEFAULT_SLABS, generate_bill_for_cycle

NORMAL_VOLTAGE = (230, 5)  # mean, stddev
NORMAL_CURRENT = (10, 2)
# Same voltage-sag shape app/scripts/simulate.py uses for --anomalous, so a
# demo-seeded anomaly looks like the same theft/loss pattern the rest of the
# project's tooling produces.
ANOMALOUS_VOLTAGE = (150, 5)
ANOMALOUS_CURRENT = (10, 2)

CLEAN_METER_CODES = ["MTR-0001", "MTR-0003", "MTR-0004", "MTR-0005"]
ANOMALOUS_METER_CODE = "MTR-0002"
PAID_BILL_METER_CODE = "MTR-0001"
UNPAID_BILL_METER_CODE = "MTR-0003"
DEMO_METER_CODES = CLEAN_METER_CODES + [ANOMALOUS_METER_CODE]

HOURS_OF_HISTORY = 6
INTERVAL_MINUTES = 3
ANOMALOUS_TAIL_MINUTES = 30  # most-recent stretch of the anomalous meter's history


def _clear_demo_data(db, meter_ids: list) -> None:
    # Delete order respects FKs: anomalies -> reading_windows -> readings.
    db.query(Anomaly).filter(Anomaly.meter_id.in_(meter_ids)).delete(synchronize_session=False)
    db.query(ReadingWindow).filter(ReadingWindow.meter_id.in_(meter_ids)).delete(synchronize_session=False)
    db.query(Reading).filter(Reading.meter_id.in_(meter_ids)).delete(synchronize_session=False)
    db.query(Bill).filter(Bill.meter_id.in_(meter_ids)).delete(synchronize_session=False)
    db.commit()


def _generate_readings(db, meter: Meter, anomalous_tail: bool) -> None:
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=HOURS_OF_HISTORY)
    # Stop comfortably before "now" so every window this generates is already
    # closed relative to floor_to_window(now) when aggregation runs next —
    # same convention as seed_training_data.py.
    end = now - timedelta(minutes=30)
    anomalous_from = end - timedelta(minutes=ANOMALOUS_TAIL_MINUTES)

    ts = start
    while ts < end:
        if anomalous_tail and ts >= anomalous_from:
            voltage = random.gauss(*ANOMALOUS_VOLTAGE)
            current = random.gauss(*ANOMALOUS_CURRENT)
        else:
            voltage = random.gauss(*NORMAL_VOLTAGE)
            current = random.gauss(*NORMAL_CURRENT)
        db.add(
            Reading(
                meter_id=meter.id,
                voltage=voltage,
                current=current,
                power=voltage * current,
                recorded_at=ts,
            )
        )
        ts += timedelta(minutes=INTERVAL_MINUTES)
    db.commit()


def _ensure_anomaly_flagged(db, meter: Meter) -> Anomaly | None:
    """Guarantees the demo's anomalous meter has an open alert regardless of
    whether a trained model.pkl happens to be loaded in this process — the
    demo dataset must be deterministic even if `python -m app.ml.train` was
    never run. If real scoring already flagged a window (model loaded and it
    scored as anomalous), this is a no-op; only steps in as a fallback.
    """
    existing = db.query(Anomaly).filter(Anomaly.meter_id == meter.id).first()
    if existing is not None:
        return existing

    window = (
        db.query(ReadingWindow)
        .filter(ReadingWindow.meter_id == meter.id)
        .order_by(ReadingWindow.window_start.desc())
        .first()
    )
    if window is None:
        return None

    window.is_anomaly = True
    window.anomaly_score = window.anomaly_score or 0.85
    window.scored_at = datetime.now(timezone.utc)
    db.flush()
    anomaly = create_anomaly_if_missing(db, window, window.anomaly_score)
    db.commit()
    return anomaly


def _ensure_no_anomalies(db, meter: Meter) -> None:
    """Guarantees a "clean" demo meter shows zero alerts. Gaussian-noise
    readings aren't guaranteed to score as in-distribution under whatever
    model.pkl happens to be trained locally — IsolationForest's contamination
    rate means a real trained model can flag a handful of false positives even
    on unremarkable data. For the demo story specifically ("these consumers
    are clean"), that's cleared here rather than trying to fight the model's
    threshold; the anomalous meter's flag is added the same way in reverse
    (see _ensure_anomaly_flagged) — actual scoring logic is untouched.
    """
    db.query(Anomaly).filter(Anomaly.meter_id == meter.id).delete(synchronize_session=False)
    db.query(ReadingWindow).filter(ReadingWindow.meter_id == meter.id).update(
        {"is_anomaly": False}, synchronize_session=False
    )
    db.commit()


def _ensure_tariff(db, admin: User, effective_by: date) -> TariffConfig:
    """A tariff must be effective on-or-before `effective_by` (the bill cycle's
    start) for generate_bill_for_cycle to find one — a tariff that exists but
    is only effective *after* that date (e.g. one submitted "today" during
    Phase 6 testing) doesn't count. Only creates a new one if nothing already
    covers that date."""
    tariff = (
        db.query(TariffConfig)
        .filter(TariffConfig.effective_from <= effective_by)
        .order_by(TariffConfig.effective_from.desc(), TariffConfig.created_at.desc())
        .first()
    )
    if tariff is not None:
        return tariff
    tariff = TariffConfig(
        effective_from=effective_by - timedelta(days=60),
        slabs=DEFAULT_SLABS,
        fixed_charge=DEFAULT_FIXED_CHARGE,
        created_by=admin.id,
    )
    db.add(tariff)
    db.commit()
    db.refresh(tariff)
    return tariff


def main():
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.role == UserRole.admin).first()
        if admin is None:
            raise SystemExit("No admin user found — run `python -m app.seed` first.")

        meters = {
            m.meter_code: m
            for m in db.query(Meter).filter(Meter.meter_code.in_(DEMO_METER_CODES)).all()
        }
        missing = [c for c in DEMO_METER_CODES if c not in meters]
        if missing:
            raise SystemExit(f"Missing meters {missing} — run `python -m app.seed` first.")

        cycle_start = date.today().replace(day=1)
        cycle_end = cycle_start + timedelta(days=27)

        _clear_demo_data(db, [m.id for m in meters.values()])
        _ensure_tariff(db, admin, effective_by=cycle_start)

        for code in CLEAN_METER_CODES:
            _generate_readings(db, meters[code], anomalous_tail=False)
            aggregate_closed_windows(db, meters[code].id)
            _ensure_no_anomalies(db, meters[code])

        _generate_readings(db, meters[ANOMALOUS_METER_CODE], anomalous_tail=True)
        aggregate_closed_windows(db, meters[ANOMALOUS_METER_CODE].id)
        anomaly = _ensure_anomaly_flagged(db, meters[ANOMALOUS_METER_CODE])

        paid_bill, paid_error = generate_bill_for_cycle(
            db, meters[PAID_BILL_METER_CODE].id, cycle_start, cycle_end
        )
        if paid_bill is not None:
            paid_bill.status = BillStatus.paid
            db.commit()

        unpaid_bill, unpaid_error = generate_bill_for_cycle(
            db, meters[UNPAID_BILL_METER_CODE].id, cycle_start, cycle_end
        )

        print("Demo dataset seeded:")
        print(f"  Clean consumers (no alerts): {', '.join(CLEAN_METER_CODES)}")
        print(
            f"  Anomalous consumer: {ANOMALOUS_METER_CODE} "
            f"({'open alert id=' + str(anomaly.id) if anomaly else 'FAILED to flag — check logs'})"
        )
        print(
            f"  Paid bill: {PAID_BILL_METER_CODE} "
            f"({'ok' if paid_bill else paid_error})"
        )
        print(
            f"  Unpaid (generated) bill: {UNPAID_BILL_METER_CODE} "
            f"({'ok' if unpaid_bill else unpaid_error})"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
