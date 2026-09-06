"""Best-effort email notification on new anomalies, via Resend's free tier
(https://resend.com/docs/api-reference/emails/send-email). Deliberately optional:
missing RESEND_API_KEY or any send failure is logged and swallowed here, never
raised — the same "degrade, don't break ingestion" pattern Phase 4 used for a
missing model.pkl.
"""

import json
import logging
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from app.config import NOTIFICATION_FROM_EMAIL, RESEND_API_KEY
from app.models.anomaly import Anomaly
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


def notify_admins_of_anomaly(db: Session, anomaly: Anomaly) -> None:
    if not RESEND_API_KEY:
        logger.warning(
            "RESEND_API_KEY not set — skipping anomaly notification email for anomaly %s.",
            anomaly.id,
        )
        return

    try:
        admin_emails = [
            email for (email,) in db.query(User.email).filter(User.role == UserRole.admin).all()
        ]
        if not admin_emails:
            return

        body = json.dumps(
            {
                "from": NOTIFICATION_FROM_EMAIL,
                "to": admin_emails,
                "subject": "Grid Watch: new theft/loss alert detected",
                "text": (
                    f"A new anomaly was flagged for meter {anomaly.meter_id}.\n"
                    f"Anomaly score: {anomaly.anomaly_score}\n"
                    f"Detected at: {anomaly.detected_at}\n"
                    "Review it in the Theft Alerts panel."
                ),
            }
        ).encode()
        req = urllib.request.Request(
            RESEND_API_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {RESEND_API_KEY}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            logger.info("Anomaly notification email sent (status=%s).", resp.status)
    except Exception:
        logger.exception(
            "Failed to send anomaly notification email for anomaly %s — continuing without it.",
            anomaly.id,
        )
