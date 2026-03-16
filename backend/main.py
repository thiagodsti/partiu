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
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .database import init_database, load_airports_if_empty
from .scheduler import start_scheduler, stop_scheduler
from .smtp_server import start_smtp_server, stop_smtp_server
from .routes import trips, flights, sync, settings, airports

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

_FRONTEND_DIR = Path(__file__).parent.parent / 'frontend' / 'dist'

# Fallback to old location if dist doesn't exist (dev mode without build)
if not _FRONTEND_DIR.exists():
    _FRONTEND_DIR = Path(__file__).parent.parent / 'frontend'


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Partiu...")
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
    title='Partiu',
    description='Personal flight tracker PWA',
    version='1.0.0',
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Include API routers
app.include_router(trips.router)
app.include_router(flights.router)
app.include_router(sync.router)
app.include_router(settings.router)
app.include_router(airports.router)


# Serve frontend static files if directory exists
if _FRONTEND_DIR.exists():
    @app.get('/manifest.json')
    def serve_manifest():
        manifest = _FRONTEND_DIR / 'manifest.json'
        if manifest.exists():
            return FileResponse(str(manifest))
        # Fall back to frontend root (manifest is not copied by Vite build)
        fallback = Path(__file__).parent.parent / 'frontend' / 'manifest.json'
        return FileResponse(str(fallback))

    @app.get('/sw.js')
    def serve_sw():
        sw = _FRONTEND_DIR / 'sw.js'
        if sw.exists():
            return FileResponse(str(sw))
        # sw.js lives in frontend/ root, not in dist/
        fallback = Path(__file__).parent.parent / 'frontend' / 'sw.js'
        return FileResponse(str(fallback))

    # Mount all built assets (Vite outputs assets/ subdir with hashed filenames)
    app.mount('/assets', StaticFiles(directory=str(_FRONTEND_DIR / 'assets')), name='assets') \
        if (_FRONTEND_DIR / 'assets').exists() else None

    @app.get('/{full_path:path}')
    def serve_spa(full_path: str):
        """Serve the SPA shell for all non-API routes."""
        # Don't catch API routes
        if full_path.startswith('api/'):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail='Not found')
        index = _FRONTEND_DIR / 'index.html'
        if index.exists():
            return FileResponse(str(index))
        return {'message': 'Frontend not built'}
