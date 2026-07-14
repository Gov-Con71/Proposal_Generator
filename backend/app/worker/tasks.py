"""Celery tasks: the ingestion pipeline (Story 2.5) and the drafting agent (Sprint 3)."""

import logging

from app.agent import run_drafting_sync
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


@celery_app.task(
    name="draft_proposal",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    acks_late=True,
)
def draft_proposal(self, rfp_id: str) -> dict:
    """Runs the drafting agent for one RFP: plan → draft → critique → persist sections.

    The agent flips processing_status to 'drafting'/'drafted'/'draft_failed'; this
    task just retries transient LLM/DB hiccups.
    """
    logger.info("Task draft_proposal received rfp_id=%s", rfp_id)
    try:
        result = run_drafting_sync(rfp_id)
        return {"rfp_id": rfp_id, "sections": result["sections"], "status": "drafted"}
    except Exception as exc:
        logger.exception("draft_proposal failed for %s", rfp_id)
        raise self.retry(exc=exc)
