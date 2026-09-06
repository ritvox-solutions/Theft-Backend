from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.user import UserOut
from app.services.auth import require_admin

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    role: UserRole | None = Query(None),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin-only: needed so the meter-creation form can offer a real consumer
    picker for the required user_id field, instead of a free-text UUID box."""
    query = db.query(User)
    if role is not None:
        query = query.filter(User.role == role)
    return query.order_by(User.name).all()
