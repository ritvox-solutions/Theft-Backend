"""Model loading + inference. The only place scoring logic lives — routers and
services import score_window() from here rather than touching the model directly.
"""

import logging
import pickle
from pathlib import Path

from app.ml.features import extract_features

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parent / "model.pkl"

_model = None


def load_model(path: Path | None = None) -> None:
    """Loads (or reloads) the module-level model. Missing file -> _model=None,
    logged as a warning, never raised — ingestion must keep working without ML."""
    global _model
    target = path or MODEL_PATH
    if not target.exists():
        logger.warning(
            "ML model not found at %s — reading_windows will be stored unscored "
            "until `python -m app.ml.train` is run.",
            target,
        )
        _model = None
        return
    with open(target, "rb") as f:
        _model = pickle.load(f)
    logger.info("ML model loaded from %s", target)


# Attempt a load at import time so a fresh process picks up an existing model.pkl.
load_model()


def score_window(window) -> tuple[bool, float] | None:
    """Returns (is_anomaly, anomaly_score) or None if no model is loaded.

    anomaly_score is the negated IsolationForest decision function: higher
    means more anomalous, lower/negative means more normal — the opposite of
    sklearn's own convention, flipped here so "sort by anomaly_score desc"
    means "most suspicious first" for callers (the future alerts UI).
    """
    if _model is None:
        return None
    features = [extract_features(window)]
    is_anomaly = bool(_model.predict(features)[0] == -1)
    anomaly_score = float(-_model.decision_function(features)[0])
    return is_anomaly, anomaly_score
