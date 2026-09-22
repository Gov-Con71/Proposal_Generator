"""Celery tasks: the ingestion pipeline (Story 2.5) and the drafting agent (Sprint 3).

Each task binds the identifier it works on into the logging context, so every
line the pipeline emits below it — in `ingestion`, `document_service`, the LLM
adapter — carries that id as a queryable field without any of those modules
needing to know about it. Combined with the request id inherited from the API
call that queued the task, one filter reconstructs the whole run.
"""

import logging

from app.agent import run_drafting_sync
from app.core import logging as applog
from app.services.export_service import run_export_render
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
    applog.bind_context(rfp_id=rfp_id)
    logger.info("Task ingest_document received rfp_id=%s", rfp_id)
    try:
        count = run_ingestion_sync(rfp_id)
        return {"rfp_id": rfp_id, "requirements": count, "status": "completed"}
    except Exception as exc:
        # `retries` is what distinguishes a transient hiccup from a genuine
        # failure in the logs — without it, three lines for one document look
        # like three separate broken uploads.
        logger.exception(
            "ingest_document failed for %s (attempt %d/%d)",
            rfp_id,
            self.request.retries + 1,
            self.max_retries + 1,
            extra={"retries": self.request.retries},
        )
        raise self.retry(exc=exc)


@celery_app.task(
    name="draft_proposal",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    acks_late=True,
)
def draft_proposal(self, proposal_id: str, retrieval_filters: dict | None = None) -> dict:
    """Runs the drafting agent for one proposal: plan → draft → critique → persist.

    Takes a **proposal id**, not an rfp id — sections belong to the proposal, so
    the agent has to know which one it is drafting. The API route authorises it
    before queueing.

    `retrieval_filters` (e.g. `{"outcome": "won"}`) is the optional knowledge-
    base pre-filter passed through from the request; None (the default) means
    every section drafts unfiltered, as before this existed.

    The agent flips processing_status to 'drafting'/'drafted'/'draft_failed'; this
    task just retries transient LLM/DB hiccups.
    """
    applog.bind_context(proposal_id=proposal_id)
    logger.info("Task draft_proposal received proposal_id=%s", proposal_id)
    try:
        result = run_drafting_sync(proposal_id, retrieval_filters=retrieval_filters)
        return {
            "proposal_id": proposal_id,
            "sections": result["sections"],
            "status": "drafted",
        }
    except Exception as exc:
        logger.exception(
            "draft_proposal failed for %s (attempt %d/%d)",
            proposal_id,
            self.request.retries + 1,
            self.max_retries + 1,
            extra={"retries": self.request.retries},
        )
        raise self.retry(exc=exc)


@celery_app.task(
    name="render_export",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    acks_late=True,
)
def render_export(self, job_id: str) -> dict:
    """Renders one export job's artifact to S3 and marks it ready.

    The export service has already flagged the row 'failed' before the
    exception reaches us; retries cover transient S3/DB hiccups.
    """
    logger.info("Task render_export received job_id=%s", job_id, extra={"job_id": job_id})
    try:
        return run_export_render(job_id)
    except Exception as exc:
        logger.exception(
            "render_export failed for %s (attempt %d/%d)",
            job_id,
            self.request.retries + 1,
            self.max_retries + 1,
            extra={"job_id": job_id, "retries": self.request.retries},
        )
        raise self.retry(exc=exc)


@celery_app.task(name='execute_dispatch_job', acks_late=True, reject_on_worker_lost=True)
def execute_dispatch_job(job_id: str) -> dict:
    from app.services.dispatch_service import execute
    return execute(job_id)
