import sys
from pathlib import Path

# Add project root to sys.path so 'app' modules resolve correctly in Vercel's serverless runtime
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.main import app

# Vercel looks for the ASGI/WSGI application instance 'app'
__all__ = ["app"]
