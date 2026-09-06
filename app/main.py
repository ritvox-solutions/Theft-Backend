from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401 — ensures all models are registered on Base.metadata
from app.config import CORS_ORIGIN_REGEX, CORS_ORIGINS
from app.database import Base, engine
from app.routers import admin, anomalies, auth, bills, billing, meters, ml, readings, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


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


@app.get("/health")
def health():
    return {"status": "ok"}
