import logging
import uuid
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError, jwt

from app.config import JWT_ALGORITHM, JWT_SECRET
from app.database import SessionLocal
from app.models.meter import Meter
from app.models.user import User
from app.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ws", tags=["websocket"])


@router.websocket("")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(None),
):
    if not token:
        logger.warning("WebSocket rejected: missing token query parameter")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id_str = payload.get("sub")
        if not user_id_str:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        user_id = uuid.UUID(user_id_str)
    except (JWTError, ValueError) as e:
        logger.warning("WebSocket rejected: invalid token (%s)", e)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        meters = db.query(Meter).filter(Meter.user_id == user.id).all()
        meter_ids = {m.id for m in meters}
        role = user.role.value
    finally:
        db.close()

    await ws_manager.connect(websocket, user_id=user_id, role=role, meter_ids=meter_ids)

    try:
        while True:
            # Await client messages / heartbeats
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.debug("WebSocket connection terminated: %s", e)
        ws_manager.disconnect(websocket)
