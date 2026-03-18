"""
Middleware for first-run detection and authentication enforcement.
"""
from starlette.middleware.base import BaseHTTPMiddleware

ALLOWED_UNAUTHENTICATED_PATHS = {
    "/api/auth/setup",
    "/api/auth/login",
    "/api/auth/me",
}


class FirstRunMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Only intercept API calls (not static assets)
        if request.url.path.startswith("/api/"):
            if request.url.path not in ALLOWED_UNAUTHENTICATED_PATHS:
                from .auth import has_any_users
                if not has_any_users():
                    from fastapi.responses import JSONResponse
                    return JSONResponse(
                        {"detail": "Setup required", "setup_required": True},
                        status_code=503
                    )
        return await call_next(request)
