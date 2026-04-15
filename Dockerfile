# ---- Frontend build ----
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

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

# Scripts (seed, etc.)
COPY scripts/ ./scripts/

# Persistent data volume mount point
RUN mkdir -p /app/data

EXPOSE 8000 2525

CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
