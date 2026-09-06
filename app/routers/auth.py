from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.auth import CurrentUserOut, LoginRequest, TokenResponse
from app.services.auth import create_access_token, get_current_user, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    token = create_access_token(user)
    return TokenResponse(access_token=token, role=user.role.value)


@router.get("/me", response_model=CurrentUserOut)
def me(current_user: User = Depends(get_current_user)):
    return CurrentUserOut.from_user(current_user)
