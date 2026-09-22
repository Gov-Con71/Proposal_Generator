# Production backend image for platforms that build from the repo root
# (default `docker build .` / PaaS auto-detect). Equivalent to
# `backend/Dockerfile.prod` when the build context is `./backend`.
#
# DUPLICATION WARNING: two production images for one service will drift, and
# already have — this one shipped an exec-form CMD binding port 8000 and 4
# workers after Dockerfile.prod had been corrected, so a root-context deploy
# would have failed its health check on the wrong port. `render.yaml` names
# `backend/Dockerfile.prod` explicitly, which is the narrower build context
# (frontend changes don't invalidate its layer cache) and makes root
# auto-detection unnecessary, so that one is the better single source. Delete
# this file if nothing else builds from the root; fix both in lockstep if
# something does.
#
# Multi-stage so the build toolchain (gcc/libpq-dev) never ships in the
# final image. Runs gunicorn with uvicorn workers as a non-root user.

# --- build stage: install dependencies into an isolated venv ---
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# --- runtime stage: slim, no toolchain, non-root ---
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# libgomp1: runtime shared lib for native wheels (onnxruntime via markitdown[all]).
# tesseract-ocr: OCR fallback for scanned/image-only PDFs (eng language data).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

RUN useradd --create-home --uid 1001 appuser
WORKDIR /code
COPY --chown=appuser:appuser backend/ .
RUN chmod +x entrypoint.sh
USER appuser

EXPOSE 8000

# Optional: set RUN_MIGRATIONS=true so entrypoint applies alembic before start.
ENTRYPOINT ["./entrypoint.sh"]

# Shell form on purpose: the managed hosts this file exists for assign the port
# through $PORT and mark a service listening anywhere else as unhealthy, and the
# exec form does not expand variables. The 8000 fallback keeps compose working.
#
# WEB_CONCURRENCY defaults to 2, not 4: each uvicorn worker loads the whole
# import graph — markitdown[all] pulls onnxruntime — so four exhaust a small
# instance before serving a request. Raise it with the instance size.
#
# --timeout is generous because the progress stream holds an SSE connection open
# for as long as ingestion runs, which has been measured in minutes.
#
# Override CMD for the Celery worker:
#   celery -A app.worker.celery_app:celery_app worker --loglevel=info --concurrency=2
CMD ["sh", "-c", "exec gunicorn app.main:app \
     -k uvicorn.workers.UvicornWorker \
     -b 0.0.0.0:${PORT:-8000} \
     --workers ${WEB_CONCURRENCY:-2} \
     --timeout ${GUNICORN_TIMEOUT:-120} \
     --access-logfile - --error-logfile -"]
