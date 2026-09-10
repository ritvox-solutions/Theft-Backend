# GridWatch Backend

GridWatch Backend is a FastAPI-based REST API and real-time processing engine for electricity theft detection, smart metering, billing, and anomaly monitoring.

## Local Development with `uv`

```bash
# Sync dependencies and virtual environment
uv sync

# Run the development server
uv run uvicorn app.main:app --reload --port 7000

# Run tests
uv run pytest
```

## Deployment on Vercel

This repository is configured for serverless deployment on Vercel:
- `api/index.py` exposes the FastAPI `app` instance.
- `vercel.json` configures serverless routing to the FastAPI app.
- Environment variables (`DATABASE_URL`, `JWT_SECRET`, etc.) should be set in the Vercel Project Settings.
