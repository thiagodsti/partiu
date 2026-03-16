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
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY backend/ ./backend/
COPY load_airports.py ./

# Frontend built assets
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
COPY frontend/manifest.json ./frontend/
COPY frontend/sw.js ./frontend/

# Persistent data volume mount point
RUN mkdir -p /app/data

EXPOSE 8000 2525

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
