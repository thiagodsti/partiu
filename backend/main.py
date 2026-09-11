"""
FastAPI application entry point.

Mounts the frontend as static files at / and all API routes under /api.
On startup: initializes database, loads airports, starts the scheduler.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .airports import routes as airports_routes
from .auth import routes as auth_routes
from .auth import validate_secret_key
from .boarding_passes import routes as boarding_passes_routes
from .database import init_database
from .day_notes import routes as day_notes_routes
from .expenses import guests_routes
from .expenses import routes as expenses_routes
from .flights import routes as flights_routes
from .limiter import limiter
from .middleware import FirstRunMiddleware
from .notifications import routes as notifications_routes
from .packing import routes as packing_routes
from .routes import version as version_routes
from .scheduler import start_scheduler, stop_scheduler
from .segments import routes as segments_routes
from .settings import routes as settings_routes
from .smtp_server import start_smtp_server, stop_smtp_server
from .stats import routes as stats_routes
from .sync import routes as sync_routes
from .trip_documents import routes as trip_documents_routes
from .trips import routes as trips_routes
from .trips import sharing_routes
from .users import routes as users_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("pdfminer.pdffont").setLevel(logging.ERROR)

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"

# Fallback to old location if dist doesn't exist (dev mode without build)
if not _FRONTEND_DIR.exists():
    _FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


def _convert_and_cleanup(jpg_path: Path, webp_path: Path) -> None:
    """Read jpg, encode as WebP, write result, delete original — runs in a thread."""
    from .integrations.wikipedia.client import _resize_and_encode_webp

    raw = jpg_path.read_bytes()
    webp_bytes = _resize_and_encode_webp(raw)
    webp_path.write_bytes(webp_bytes)
    jpg_path.unlink(missing_ok=True)


async def _migrate_images_to_webp() -> None:
    """Convert any legacy .jpg trip images to WebP in the background at startup."""
    from .integrations.wikipedia.client import _images_dir

    images_dir = _images_dir()
    jpg_files = list(images_dir.glob("*.jpg"))
    if not jpg_files:
        return
    logger.info("Migrating %d legacy trip image(s) to WebP…", len(jpg_files))
    converted = 0
    for jpg_path in jpg_files:
        webp_path = jpg_path.with_suffix(".webp")
        if webp_path.exists():
            await asyncio.to_thread(jpg_path.unlink, missing_ok=True)
            continue
        try:
            await asyncio.to_thread(_convert_and_cleanup, jpg_path, webp_path)
            converted += 1
        except Exception as exc:
            logger.warning("Could not convert %s: %s", jpg_path.name, exc)
    logger.info("WebP migration complete (%d converted)", converted)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Partiu...")
    validate_secret_key()  # Fail loudly if SECRET_KEY is not configured
    init_database()
    from .airports.repository import AirportRepository

    _airports = AirportRepository()
    _airports.load_from_csv_if_empty()
    # Databases seeded before the ranking columns existed need a one-time
    # backfill; airport name resolution ranks on them.
    _airports.backfill_rank_columns()
    from .notifications import push_service

    push_service.ensure_vapid_keys()
    # Reset any sync states left as "running" from a previous crash/kill
    from .database import db_write

    with db_write() as conn:
        stale = conn.execute(
            "UPDATE email_sync_state SET status = 'idle' WHERE status = 'running'"
        ).rowcount
    if stale:
        logger.warning("Reset %d stale 'running' sync state(s) from previous crash", stale)
    start_scheduler()
    start_smtp_server()
    asyncio.create_task(_migrate_images_to_webp())
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
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.add_middleware(
    CORSMiddleware,  # type: ignore[arg-type]
    allow_origins=[],  # No cross-origin access — app is served same-origin
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.add_middleware(FirstRunMiddleware)  # type: ignore[arg-type]

# Include API routers
# NOTE: sharing_routes MUST be registered BEFORE trips router to avoid
# /api/trips/invitations being matched by trips' /{trip_id} catch-all route.
app.include_router(auth_routes.router)
app.include_router(users_routes.router)
app.include_router(sharing_routes.router)
app.include_router(trips_routes.router)
app.include_router(flights_routes.router)
app.include_router(sync_routes.router)
app.include_router(settings_routes.router)
app.include_router(airports_routes.router)
app.include_router(stats_routes.router)
app.include_router(notifications_routes.router)
app.include_router(boarding_passes_routes.router)
app.include_router(day_notes_routes.router)
app.include_router(expenses_routes.router)
app.include_router(guests_routes.router)
app.include_router(packing_routes.router)
app.include_router(segments_routes.router)
app.include_router(trip_documents_routes.router)
app.include_router(version_routes.router)


# Serve frontend static files if directory exists
if _FRONTEND_DIR.exists():

    @app.get("/manifest.json")
    def serve_manifest():
        manifest = _FRONTEND_DIR / "manifest.json"
        if manifest.exists():
            return FileResponse(str(manifest))
        # Dev mode: manifest lives in public/, not in frontend root
        fallback = Path(__file__).parent.parent / "frontend" / "public" / "manifest.json"
        return FileResponse(str(fallback))

    # Never let browsers cache the service worker script or the SPA shell:
    # both must be revalidated on every request so a new deploy is picked up
    # promptly instead of being served stale from the HTTP cache.
    _NO_CACHE_HEADERS = {"Cache-Control": "no-cache"}

    @app.get("/sw.js")
    def serve_sw():
        sw = _FRONTEND_DIR / "sw.js"
        if sw.exists():
            return FileResponse(str(sw), headers=_NO_CACHE_HEADERS)
        # sw.js lives in frontend/ root, not in dist/
        fallback = Path(__file__).parent.parent / "frontend" / "sw.js"
        return FileResponse(str(fallback), headers=_NO_CACHE_HEADERS)

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
            return FileResponse(str(index), headers=_NO_CACHE_HEADERS)
        return {"message": "Frontend not built"}
