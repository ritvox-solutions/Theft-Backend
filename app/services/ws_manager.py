import asyncio
import logging
import uuid
from typing import Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections from clients (consumers and admins),
    supporting both async and thread-safe cross-thread broadcasting from background MQTT threads.
    """

    def __init__(self):
        # Maps WebSocket connection -> {"user_id": UUID, "role": str, "meter_ids": set[UUID]}
        self.active_connections: dict[WebSocket, dict[str, Any]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    async def connect(self, websocket: WebSocket, user_id: uuid.UUID, role: str, meter_ids: set[uuid.UUID]):
        await websocket.accept()
        self.active_connections[websocket] = {
            "user_id": user_id,
            "role": role,
            "meter_ids": meter_ids,
        }
        logger.info("WebSocket client connected: user %s (%s)", user_id, role)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            meta = self.active_connections.pop(websocket)
            logger.info("WebSocket client disconnected: user %s", meta.get("user_id"))

    async def broadcast(self, data: dict[str, Any], target_meter_id: uuid.UUID | None = None):
        """Sends data to connected clients. Admins receive all updates;
        consumers receive only updates matching their assigned meter(s).
        """
        stale_connections = []
        for ws, meta in list(self.active_connections.items()):
            role = meta.get("role")
            meter_ids = meta.get("meter_ids", set())

            # Check if this connection should receive the message
            if role == "admin" or target_meter_id is None or target_meter_id in meter_ids:
                try:
                    await ws.send_json(data)
                except Exception as e:
                    logger.warning("Error sending WebSocket message: %s", e)
                    stale_connections.append(ws)

        for ws in stale_connections:
            self.disconnect(ws)

    def broadcast_threadsafe(self, data: dict[str, Any], target_meter_id: uuid.UUID | None = None):
        """Thread-safe entry point to push messages from background threads (e.g., MQTT listener)
        into the main FastAPI asyncio event loop.
        """
        if self.loop is not None and self.loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self.broadcast(data, target_meter_id), self.loop)
            except Exception as e:
                logger.error("Failed to schedule WebSocket broadcast: %s", e)
        else:
            logger.debug("Event loop not available for WebSocket broadcast")


ws_manager = ConnectionManager()
