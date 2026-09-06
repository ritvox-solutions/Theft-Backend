"""Trains the Isolation Forest and writes app/ml/model.pkl — the one and only
copy of the model. Runnable standalone: `python -m app.ml.train`.

Also called by POST /api/ml/retrain (app/routers/ml.py) — both paths go
through train_model() so there is exactly one training code path.
"""

import pickle

from sklearn.ensemble import IsolationForest
from sqlalchemy.orm import Session

from app.ml.features import extract_features
from app.ml.predict import MODEL_PATH
from app.models.meter import Meter
from app.models.reading_window import ReadingWindow

# MTR-TRAIN is a dedicated, admin-owned reference meter seeded purely with
# clearly-normal simulated data (see app/scripts/seed_training_data.py) — kept
# separate from the demo consumer meters (MTR-0001..0005), which may carry
# manually-injected anomalous test data from the Phase 2 simulator and must
# never be used as "normal" training examples.
TRAINING_METER_CODE = "MTR-TRAIN"
MIN_TRAINING_WINDOWS = 10


def train_model(db: Session) -> dict:
    windows = (
        db.query(ReadingWindow)
        .join(Meter, Meter.id == ReadingWindow.meter_id)
        .filter(Meter.meter_code == TRAINING_METER_CODE)
        .all()
    )
    if len(windows) < MIN_TRAINING_WINDOWS:
        raise ValueError(
            f"Only {len(windows)} reading_windows found for training meter "
            f"'{TRAINING_METER_CODE}' (need at least {MIN_TRAINING_WINDOWS}). "
            "Run `python -m app.scripts.seed_training_data` first."
        )

    X = [extract_features(w) for w in windows]

    model = IsolationForest(contamination=0.05, n_estimators=100, random_state=42)
    model.fit(X)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)

    return {"windows_used": len(windows), "model_path": str(MODEL_PATH)}


def main():
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = train_model(db)
        print(
            f"Trained on {result['windows_used']} windows. "
            f"Model saved to {result['model_path']}."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
