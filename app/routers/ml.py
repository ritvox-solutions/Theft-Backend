from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.ml import predict
from app.ml.train import train_model
from app.models.user import User
from app.services.auth import require_admin

router = APIRouter(prefix="/api/ml", tags=["ml"])


@router.post("/retrain")
def retrain(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    try:
        result = train_model(db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    predict.load_model()  # hot-reload into this already-running process
    return {"status": "ok", **result}
