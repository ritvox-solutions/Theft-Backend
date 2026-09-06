"""Bulk-generates clean, normal-only historical readings for the MTR-TRAIN
reference meter, then aggregates them into reading_windows — the training
corpus for `python -m app.ml.train`.

Run `python -m app.seed` first (creates MTR-TRAIN). Then:
    python -m app.scripts.seed_training_data

Inserts Reading rows directly via the DB session rather than posting through
the real HTTP endpoint (unlike Phase 2's simulator) — generating 24 hours of
data one HTTP round-trip at a time would be impractically slow for a seed
script, and this is training-corpus setup, not an ingestion-path exercise.
Reuses aggregate_closed_windows() from Phase 2 for the actual rollup, so
there's still only one aggregation implementation.
"""

import random
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models.meter import Meter
from app.models.reading import Reading
from app.services.aggregation import aggregate_closed_windows

TRAINING_METER_CODE = "MTR-TRAIN"
HOURS_OF_HISTORY = 24
INTERVAL_MINUTES = 3
NORMAL_VOLTAGE = (230, 5)  # mean, stddev
NORMAL_CURRENT = (10, 2)


def generate_readings(db, meter: Meter) -> int:
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=HOURS_OF_HISTORY)
    # Stop comfortably before "now" so every window this generates is already
    # closed relative to floor_to_window(now) when aggregation runs next.
    end = now - timedelta(minutes=30)

    count = 0
    ts = start
    while ts < end:
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
        count += 1
        ts += timedelta(minutes=INTERVAL_MINUTES)

    db.commit()
    return count


def main():
    db = SessionLocal()
    try:
        meter = db.query(Meter).filter(Meter.meter_code == TRAINING_METER_CODE).first()
        if meter is None:
            raise SystemExit(
                f"Meter '{TRAINING_METER_CODE}' not found — run `python -m app.seed` first."
            )

        reading_count = generate_readings(db, meter)
        windows = aggregate_closed_windows(db, meter.id)
        print(
            f"Inserted {reading_count} normal readings for {TRAINING_METER_CODE}, "
            f"aggregated into {len(windows)} reading_windows."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
