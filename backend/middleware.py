"""
Middleware for first-run detection, authentication enforcement, and security headers.
"""

from starlette.middleware.base import BaseHTTPMiddleware

ALLOWED_UNAUTHENTICATED_PATHS = {
    "/api/auth/setup",
    "/api/auth/login",
    "/api/auth/me",
}

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    # Tell browsers to only connect via HTTPS for the next year (ignored on HTTP)
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    # CSP: same-origin scripts/styles; inline styles allowed (Svelte); data: for QR SVGs
    # frame-src allows the OpenStreetMap embed; img-src allows Wikipedia thumbnails served locally
    # CartoDB tile servers and unpkg needed for the trip route map (Leaflet)
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https://*.basemaps.cartocdn.com https://*.tile.openstreetmap.org; "
        "connect-src 'self' https://*.basemaps.cartocdn.com https://*.tile.openstreetmap.org; "
        "frame-src https://www.openstreetmap.org; "
        "frame-ancestors 'none';"
    ),
}


class FirstRunMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Block unauthenticated API access before setup is complete
        if request.url.path.startswith("/api/"):
            if request.url.path not in ALLOWED_UNAUTHENTICATED_PATHS:
                from .auth import has_any_users

                if not has_any_users():
                    from fastapi.responses import JSONResponse

                    return JSONResponse(
                        {"detail": "Setup required", "setup_required": True}, status_code=503
                    )

        response = await call_next(request)

        # Add security headers to every response
        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value

        return response
