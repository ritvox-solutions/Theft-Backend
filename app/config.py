import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Comma-separated list of allowed browser origins for CORS. Defaults to the Vite
# dev server on both host spellings — a browser treats http://localhost:5173 and
# http://127.0.0.1:5173 as distinct origins, and a preflight from the wrong one
# gets a 400 from Starlette's CORS middleware.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

# Regex fallback matched against the request Origin when it isn't in CORS_ORIGINS.
# Default accepts localhost / 127.0.0.1 on ANY port, so a Vite dev server that
# fell back to 5174+ still works without editing .env. Set to "" to disable.
CORS_ORIGIN_REGEX = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
)
JWT_SECRET = os.getenv("JWT_SECRET", "changeme-dev-only")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

# Resend (https://resend.com) free-tier transactional email, used for new-anomaly
# admin notifications. Optional: unset -> notifications are skipped, logged, never fatal.
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
NOTIFICATION_FROM_EMAIL = os.getenv("NOTIFICATION_FROM_EMAIL", "alerts@gridwatch.dev")
