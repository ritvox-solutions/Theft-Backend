import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401 — ensures all models are registered on Base.metadata
from app.config import CORS_ORIGIN_REGEX, CORS_ORIGINS
from app.database import Base, engine
from app.routers import admin, anomalies, auth, bills, billing, meters, ml, readings, users, ws
from app.services.mqtt_service import start_mqtt, stop_mqtt
from app.services.ws_manager import ws_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    import os

    # Attempt table creation safely
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logging.getLogger(__name__).warning("Could not auto-create tables during startup: %s", e)

    try:
        ws_manager.set_loop(asyncio.get_running_loop())
    except Exception:
        pass

    # Background MQTT listener runs in persistent environments (local / VM / Docker),
    # but is disabled in ephemeral Vercel serverless functions to avoid cold-start timeouts.
    is_vercel = bool(os.getenv("VERCEL"))
    if not is_vercel:
        start_mqtt()

    try:
        yield
    finally:
        if not is_vercel:
            stop_mqtt()


app = FastAPI(title="Grid Watch API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(meters.router)
app.include_router(readings.router)
app.include_router(anomalies.router)
app.include_router(ml.router)
app.include_router(admin.router)
app.include_router(users.router)
app.include_router(billing.router)
app.include_router(bills.router)
app.include_router(ws.router)


@app.get("/health")
def health():
    return {"status": "ok"}
