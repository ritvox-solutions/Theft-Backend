from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.reading_window import ReadingWindow
from app.models.user import User
from app.services.auth import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats")
def get_stats(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    energy_today_kwh = (
        db.query(func.coalesce(func.sum(ReadingWindow.energy_kwh), 0))
        .filter(ReadingWindow.window_start >= today_start)
        .scalar()
    )
    return {"energy_today_kwh": float(energy_today_kwh)}
