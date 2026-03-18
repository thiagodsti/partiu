"""
FastAPI application entry point.

Mounts the frontend as static files at / and all API routes under /api.
On startup: initializes database, loads airports, starts the scheduler.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .auth import validate_secret_key
from .database import init_database, load_airports_if_empty
from .limiter import limiter
from .middleware import FirstRunMiddleware
from .routes import airports, flights, settings, sync, trips
from .routes import auth as auth_routes
from .routes import users as users_routes
from .scheduler import start_scheduler, stop_scheduler
from .smtp_server import start_smtp_server, stop_smtp_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"

# Fallback to old location if dist doesn't exist (dev mode without build)
if not _FRONTEND_DIR.exists():
    _FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Partiu...")
    validate_secret_key()  # Fail loudly if SECRET_KEY is not configured
    init_database()
    load_airports_if_empty()
    start_scheduler()
    start_smtp_server()
    logger.info("Startup complete")
    yield
    # Shutdown
    stop_smtp_server()
    stop_scheduler()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Partiu",
    description="Personal flight tracker PWA",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # No cross-origin access — app is served same-origin
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.add_middleware(FirstRunMiddleware)

# Include API routers
app.include_router(auth_routes.router)
app.include_router(users_routes.router)
app.include_router(trips.router)
app.include_router(flights.router)
app.include_router(sync.router)
app.include_router(settings.router)
app.include_router(airports.router)


# Serve frontend static files if directory exists
if _FRONTEND_DIR.exists():

    @app.get("/manifest.json")
    def serve_manifest():
        manifest = _FRONTEND_DIR / "manifest.json"
        if manifest.exists():
            return FileResponse(str(manifest))
        # Fall back to frontend root (manifest is not copied by Vite build)
        fallback = Path(__file__).parent.parent / "frontend" / "manifest.json"
        return FileResponse(str(fallback))

    @app.get("/sw.js")
    def serve_sw():
        sw = _FRONTEND_DIR / "sw.js"
        if sw.exists():
            return FileResponse(str(sw))
        # sw.js lives in frontend/ root, not in dist/
        fallback = Path(__file__).parent.parent / "frontend" / "sw.js"
        return FileResponse(str(fallback))

    # Mount all built assets (Vite outputs assets/ subdir with hashed filenames)
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIR / "assets")), name="assets") if (
        _FRONTEND_DIR / "assets"
    ).exists() else None

    _FRONTEND_PUBLIC = Path(__file__).parent.parent / "frontend" / "public"

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        """Serve static files or the SPA shell for all non-API routes."""
        if full_path.startswith("api/"):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Not found")
        # Serve real static files (icons, manifest fall-through, etc.)
        for base in (_FRONTEND_DIR, _FRONTEND_PUBLIC):
            candidate = base / full_path
            if candidate.exists() and candidate.is_file():
                return FileResponse(str(candidate))
        # SPA: all other paths get index.html
        index = _FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"message": "Frontend not built"}
