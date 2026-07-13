"""Celery tasks for the ingestion pipeline (Story 2.5)."""

import logging

from app.services.ingestion import run_ingestion_sync
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="ingest_document",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    acks_late=True,
)
def ingest_document(self, rfp_id: str) -> dict:
    """Runs parse → extract → DB insert for one uploaded RFP document.

    Retries transient failures (e.g. S3/LLM hiccups); the ingestion service has
    already flagged the row 'failed' before the exception reaches us.
    """
    logger.info("Task ingest_document received rfp_id=%s", rfp_id)
    try:
        count = run_ingestion_sync(rfp_id)
        return {"rfp_id": rfp_id, "requirements": count, "status": "completed"}
    except Exception as exc:
        logger.exception("ingest_document failed for %s", rfp_id)
        raise self.retry(exc=exc)
