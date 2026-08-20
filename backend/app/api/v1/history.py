"""Past-performance ingestion endpoints (Story 3.1; per-bid scope added Sprint 9).

    POST   /history          → chunk + embed + store past-performance TEXT
    POST   /history/upload   → same, from an uploaded PDF/DOCX/TXT document
    GET    /history          → list ingested sources in one pool
    DELETE /history/{source} → remove one source from one pool

Every route takes an optional `proposalId`, which picks the evidence pool:

  * absent  — the tenant's long-term library, reusable across every bid
  * present — supporting documents for that one proposal, removed with it

Feeds the RAG retrieval used by the draft writer, which prefers a bid's own
documents and falls back to the library (see `retrieval.search_similar`).
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.core.config import settings
from app.core.deps import get_current_user_id, require_writer
from app.models.contract import HistoryIngestRequest, HistoryIngestResponse, HistorySource
from app.services import history_service as history
from app.services import proposals_service
from app.services.document_parser import DocumentParseError, parse_to_markdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/history", tags=["History (RAG)"])

# Same set the RFP upload accepts — past-performance evidence arrives as the
# same kinds of document, and it goes through the same parser.
ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt"}


async def _resolve_pool(proposal_id: Optional[UUID], user_id: UUID) -> Optional[UUID]:
    """Validates the requested pool and returns it.

    A proposal the caller does not own is refused as 404 rather than 403 — the
    same existence-oracle rule the rest of the API follows, so a probe cannot
    learn which proposal ids are real.
    """
    if proposal_id is None:
        return None
    owned = await asyncio.to_thread(proposals_service.exists_owned, proposal_id, user_id)
    if not owned:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return proposal_id


@router.post(
    "",
    response_model=HistoryIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest past-performance text into the vector store",
    dependencies=[Depends(require_writer)],
)
async def ingest(
    payload: HistoryIngestRequest,
    proposal_id: Optional[UUID] = Query(None, alias="proposalId"),
    user_id: UUID = Depends(get_current_user_id),
) -> HistoryIngestResponse:
    pool = await _resolve_pool(proposal_id, user_id)
    count = await asyncio.to_thread(
        history.store_history,
        user_id,
        payload.source_name,
        payload.content,
        pool,
        industry=payload.industry,
        document_type=payload.document_type,
        outcome=payload.outcome,
    )
    return HistoryIngestResponse(source_name=payload.source_name, chunks=count)


@router.post(
    "/upload",
    response_model=HistoryIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a past-performance document into the vector store",
    dependencies=[Depends(require_writer)],
)
async def upload(
    file: UploadFile = File(...),
    proposal_id: Optional[UUID] = Form(None, alias="proposalId"),
    user_id: UUID = Depends(get_current_user_id),
) -> HistoryIngestResponse:
    """Parses a document to text, then chunks, embeds and stores it.

    Handled inline rather than on the worker: `embed_texts` sends every chunk
    in ONE provider call, so a document costs a single request no matter how
    many chunks it yields. A queued task would buy nothing here and would cost
    a status surface for documents that exist but are not yet searchable.
    """
    pool = await _resolve_pool(proposal_id, user_id)

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported file type '{suffix}'. Allowed: {sorted(ALLOWED_SUFFIXES)}",
        )

    # Read with a hard ceiling. Reading first and checking after would let an
    # oversized upload occupy memory before it is refused.
    body = await file.read(settings.max_upload_bytes + 1)
    if len(body) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)}MB limit.",
        )
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")

    tmp_dir = tempfile.mkdtemp(prefix="history_upload_")
    # Keep the original suffix so the parser can detect the file type.
    local_path = str(Path(tmp_dir) / (file.filename or "document.pdf"))
    try:
        with open(local_path, "wb") as fh:
            fh.write(body)
        try:
            text = await parse_to_markdown(local_path)
        except DocumentParseError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Could not read '{file.filename}': {exc}",
            ) from exc

        if not text.strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"No text could be extracted from '{file.filename}'. "
                "A scanned document needs OCR before it can be used as evidence.",
            )

        source_name = Path(file.filename or "document").stem
        count = await asyncio.to_thread(
            history.store_history, user_id, source_name, text, pool
        )
    finally:
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass

    logger.info(
        "history upload: '%s' → %d chunk(s) (%s)",
        source_name,
        count,
        f"proposal {pool}" if pool else "library",
    )
    return HistoryIngestResponse(source_name=source_name, chunks=count)


@router.get("", response_model=list[HistorySource], summary="List ingested history sources")
async def sources(
    proposal_id: Optional[UUID] = Query(None, alias="proposalId"),
    user_id: UUID = Depends(get_current_user_id),
) -> list[HistorySource]:
    pool = await _resolve_pool(proposal_id, user_id)
    rows = await asyncio.to_thread(history.list_sources, user_id, pool)
    return [HistorySource(**s) for s in rows]


@router.delete(
    "/{source_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove one source from one pool",
    dependencies=[Depends(require_writer)],
)
async def remove(
    source_name: str,
    proposal_id: Optional[UUID] = Query(None, alias="proposalId"),
    user_id: UUID = Depends(get_current_user_id),
) -> None:
    pool = await _resolve_pool(proposal_id, user_id)
    deleted = await asyncio.to_thread(history.delete_source, user_id, source_name, pool)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
