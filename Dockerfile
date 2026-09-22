# Production backend image for platforms that build from the repo root
# (default `docker build .` / PaaS auto-detect). Equivalent to
# `backend/Dockerfile.prod` when the build context is `./backend`.
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

# 4 uvicorn workers behind gunicorn. Tune -w to CPU count on the target host.
# Override CMD for the Celery worker:
#   celery -A app.worker.celery_app:celery_app worker --loglevel=info --concurrency=2
CMD ["gunicorn", "app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "4", "-b", "0.0.0.0:8000", \
     "--access-logfile", "-", "--error-logfile", "-"]
