# ---- Frontend build ----
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

# ---- KDE Itinerary extractor (optional extraction tier) ----
# KDE's static build: one binary plus translations, ~35 MB, needs only glibc.
# x86_64 only, so other architectures get an empty folder and the tier simply
# reports itself as not installed. Version and checksum are pinned; see
# scripts/fetch_kitinerary.py for how to bump them.
FROM python:3.12-slim AS kitinerary
ARG TARGETARCH
ARG KITINERARY_VERSION=26.04.3
ARG KITINERARY_SHA256=ed2d1da43e2299a944f25b1521cb40183bbf9bc7691fa0f3d53a69c118dff778
COPY scripts/fetch_kitinerary.py /tmp/fetch_kitinerary.py
RUN mkdir -p /opt/kitinerary \
    && if [ "$TARGETARCH" = "amd64" ]; then \
         python /tmp/fetch_kitinerary.py "$KITINERARY_VERSION" "$KITINERARY_SHA256" /opt/kitinerary; \
       fi

# ---- Backend / final image ----
FROM python:3.12-slim
WORKDIR /app

# System deps for lxml / pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# App code
COPY backend/ ./backend/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY load_airports.py ./

# Frontend built assets (manifest.json is already in dist/ via public/)
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
COPY frontend/sw.js ./frontend/

# Locale JSONs — the backend translates notification text with these, and the
# built frontend bundles them into JS, so they must ship as files too.
COPY frontend/src/locales ./backend/locales

# Scripts (seed, etc.)
COPY scripts/ ./scripts/

# KDE Itinerary extractor (empty on non-x86_64 builds)
COPY --from=kitinerary /opt/kitinerary /opt/kitinerary

# Persistent data volume mount point
RUN mkdir -p /app/data

EXPOSE 8000 2525

# --no-sync: run the environment built above as it is. A plain `uv run` syncs
# the project's default groups first, which include `dev` — so every container
# start downloaded pytest, ruff, ty and vulture from PyPI (seen in production
# logs), and a start with PyPI unreachable could fail outright.
CMD ["uv", "run", "--no-sync", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
