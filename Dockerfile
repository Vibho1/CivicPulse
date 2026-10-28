# CivicPulse: single-container image (PWA + API) for Cloud Run / any Docker host.
#   docker build -t civicpulse .
#   docker run -p 8080:8080 -e GEMINI_API_KEY=... civicpulse
# Cloud Run (SQLite kept in Cloud Storage via Litestream, uploads on a bucket mount):
#   Terraform in deploy/terraform (walkthrough: docs/DEPLOY_GCP.md)

# ---- 1. build the PWA -------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. runtime -------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
# Litestream streams the SQLite DB to Cloud Storage when LITESTREAM_REPLICA_URL is set
# (see deploy/entrypoint.sh); without it the API starts exactly as before.
ARG LITESTREAM_VERSION=0.3.13
ADD https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.tar.gz /tmp/litestream.tar.gz
RUN tar -C /usr/local/bin -xzf /tmp/litestream.tar.gz && rm /tmp/litestream.tar.gz
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist
COPY deploy/entrypoint.sh /usr/local/bin/civicpulse-entrypoint
RUN chmod +x /usr/local/bin/civicpulse-entrypoint
# Persist DB + uploads under /app/backend/data (mount a volume in production).
VOLUME ["/app/backend/data"]
WORKDIR /app/backend
EXPOSE 8080
CMD ["civicpulse-entrypoint"]
