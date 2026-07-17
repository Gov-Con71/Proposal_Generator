"""Ingestion orchestrator (Story 2.5).

Drives the full async pipeline for one uploaded document:

    S3 download → parse to Markdown → LLM compliance extraction → DB insert

Exposed as both an async coroutine (`run_ingestion`) and a sync entry point
(`run_ingestion_sync`) so the Celery worker — which runs synchronously — can
invoke it via `asyncio.run`.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from uuid import UUID

from app.core import cache
from app.services import document_service as docs
from app.services.compliance_extractor import run_extraction
from app.services.document_parser import DocumentParseError, parse_to_markdown
from app.services.guardrails import sanitize_matrix
from app.services.s3_storage import S3Storage

logger = logging.getLogger(__name__)


async def run_ingestion(rfp_id: UUID) -> int:
    """Processes a single document end to end. Returns the requirement count.

    Advances processing_status as it goes and flips the row to 'failed' on any
    error (re-raising so the worker records the failure too).
    """
    document = docs.get_document(rfp_id)
    s3_key = document["s3_storage_key"]
    file_name = document["file_name"]
    logger.info("Ingestion start: rfp=%s key=%s", rfp_id, s3_key)

    tmp_dir = tempfile.mkdtemp(prefix="rfp_ingest_")
    # Preserve the original suffix so MarkItDown can detect the file type.
    local_path = str(Path(tmp_dir) / (file_name or "document.pdf"))

    try:
        docs.update_status(rfp_id, "parsing")
        S3Storage().download_to_path(s3_key, local_path)

        markdown_text = await parse_to_markdown(local_path)

        docs.update_status(rfp_id, "extracting")
        matrix = await run_extraction(markdown_text)

        # Guardrail: drop malformed/hallucinated/duplicate items before persisting.
        matrix, rejected = sanitize_matrix(matrix)
        if rejected:
            logger.info("Ingestion rfp=%s: guardrails rejected %d requirement(s)", rfp_id, rejected)

        count = docs.insert_requirements(rfp_id, matrix)
        docs.update_status(rfp_id, "completed")

        # The read routes cache requirements/compliance per (tenant, rfp). The
        # process page polls while ingestion runs, so an empty list is almost
        # always cached before the worker inserts anything — without this the
        # workspace shows "no requirements yet" for a full TTL after a
        # successful extraction. The worker writes straight to the DB, so it
        # must evict what the API cached on its behalf.
        owner = document["uploaded_by"]
        cache.cache_delete(
            cache.requirements_key(owner, rfp_id),
            cache.compliance_key(owner, rfp_id),
            cache.sections_key(owner, rfp_id),
        )

        logger.info("Ingestion complete: rfp=%s requirements=%d", rfp_id, count)
        return count
    except DocumentParseError:
        docs.update_status(rfp_id, "failed")
        logger.exception("Ingestion failed (parse) for rfp=%s", rfp_id)
        raise
    except Exception:
        docs.update_status(rfp_id, "failed")
        logger.exception("Ingestion failed for rfp=%s", rfp_id)
        raise
    finally:
        # Best-effort temp cleanup
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass


def run_ingestion_sync(rfp_id: UUID) -> int:
    """Synchronous wrapper for the Celery worker."""
    return asyncio.run(run_ingestion(UUID(str(rfp_id))))
