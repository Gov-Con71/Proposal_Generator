"""Real document ingestion endpoints (Stories 2.2 + 2.5).

    POST /documents/upload            → stream to S3, create row, enqueue worker
    GET  /documents/{rfp_id}          → poll processing status (drives UI progress)
    POST /documents/{rfp_id}/reanalyze → re-run the pipeline

Mounted without the /api/v1 prefix so paths match the frontend client
(`documentsApi` in proposalai-frontend/lib/api).
"""

import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.config import settings
from app.core.deps import get_current_user_id, require_writer
from app.models.contract import CamelModel, ProposalCreate
from app.services import document_service as docs
from app.services import proposals_service as proposals
from app.services.s3_storage import S3Storage
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])

ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt"}


class DocumentUploadResponse(CamelModel):
    # The proposal created for this upload. It is the id the client navigates
    # by — every /proposals/{id}/… route is keyed on it (GAP_ANALYSIS §1.2).
    proposal_id: str
    rfp_id: str
    file_name: str
    size_bytes: int
    s3_key: str
    processing_status: str


class DocumentStatusResponse(CamelModel):
    rfp_id: str
    file_name: str
    processing_status: str
    requirements_count: int


def _owned_document_or_404(rfp_id: UUID, uploaded_by: UUID) -> dict:
    """Fetches a document, treating cross-tenant access as 'not found'."""
    try:
        document = docs.get_document(rfp_id)
    except docs.DocumentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if str(document["uploaded_by"]) != str(uploaded_by):
        # Don't leak existence of other tenants' documents.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    return document


def _spooled_size(upload: UploadFile) -> int:
    """Measures the (already spooled) upload without loading it into memory."""
    f = upload.file
    f.seek(0, 2)  # SEEK_END
    size = f.tell()
    f.seek(0)
    return size


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload an RFP document, store it in S3, and queue ingestion",
    dependencies=[Depends(require_writer)],
)
async def upload_document(
    file: UploadFile = File(..., description="RFP file (PDF, DOCX, or TXT)."),
    uploaded_by: UUID = Depends(get_current_user_id),
) -> DocumentUploadResponse:
    # --- validate type (2.1 error-boundary contract) ---
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(ALLOWED_SUFFIXES)}",
        )

    # --- validate size ---
    size = _spooled_size(file)
    if size == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty.")
    if size > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)}MB limit.",
        )

    # --- tenant-isolated S3 key: uploads/{user}/{rfp}/{filename} ---
    rfp_id = uuid4()
    safe_name = Path(file.filename or "document.pdf").name
    s3_key = f"uploads/{uploaded_by}/{rfp_id}/{safe_name}"

    try:
        S3Storage().stream_upload(s3_key, file.file, file.content_type)
    except Exception as exc:  # noqa: BLE001 — surface storage failures cleanly
        logger.exception("S3 upload failed for key %s", s3_key)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Storage upload failed: {exc}"
        ) from exc

    # --- persist row (reuse the app-generated id so key + row agree) ---
    try:
        created_id = docs.create_rfp_document(uploaded_by, safe_name, s3_key)
    except docs.UnknownUploaderError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown uploader '{uploaded_by}' — user does not exist.",
        ) from exc

    # --- create the proposal this upload is for ---
    # Uploading an RFP is how a proposal starts, so one is created here rather
    # than leaving an orphan document the dashboard can never show. The title is
    # a placeholder the user renames; ingestion fills in the rest.
    proposal = proposals.create_proposal(
        uploaded_by,
        ProposalCreate(title=Path(safe_name).stem, document_id=str(created_id)),
    )

    # --- hand off to the async worker queue (by name; worker owns the LLM stack) ---
    celery_app.send_task("ingest_document", args=[str(created_id)])

    return DocumentUploadResponse(
        proposal_id=proposal.id,
        rfp_id=str(created_id),
        file_name=safe_name,
        size_bytes=size,
        s3_key=s3_key,
        processing_status="pending",
    )


@router.get(
    "/{rfp_id}",
    response_model=DocumentStatusResponse,
    summary="Poll ingestion status for a document",
)
def get_status(
    rfp_id: UUID, uploaded_by: UUID = Depends(get_current_user_id)
) -> DocumentStatusResponse:
    document = _owned_document_or_404(rfp_id, uploaded_by)
    return DocumentStatusResponse(
        rfp_id=str(document["rfp_id"]),
        file_name=document["file_name"],
        processing_status=document["processing_status"],
        requirements_count=docs.count_requirements(rfp_id),
    )


@router.post(
    "/{rfp_id}/reanalyze",
    response_model=DocumentStatusResponse,
    summary="Re-run the ingestion pipeline for a document",
    dependencies=[Depends(require_writer)],
)
def reanalyze(
    rfp_id: UUID, uploaded_by: UUID = Depends(get_current_user_id)
) -> DocumentStatusResponse:
    document = _owned_document_or_404(rfp_id, uploaded_by)
    docs.update_status(rfp_id, "pending")
    celery_app.send_task("ingest_document", args=[str(rfp_id)])
    return DocumentStatusResponse(
        rfp_id=str(rfp_id),
        file_name=document["file_name"],
        processing_status="pending",
        requirements_count=docs.count_requirements(rfp_id),
    )


@router.post(
    "/{rfp_id}/draft",
    response_model=DocumentStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate a full proposal draft with the AI writer agent (async)",
    dependencies=[Depends(require_writer)],
)
def draft_proposal(
    rfp_id: UUID, uploaded_by: UUID = Depends(get_current_user_id)
) -> DocumentStatusResponse:
    """Queues the drafting agent. Poll GET /documents/{rfp_id} for status
    ('drafting' → 'drafted') and GET /proposals/{rfp_id}/sections for results."""
    document = _owned_document_or_404(rfp_id, uploaded_by)
    requirements_count = docs.count_requirements(rfp_id)
    if requirements_count == 0:
        # Drafting is grounded in the extracted compliance matrix.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No requirements extracted yet — ingest the RFP before drafting.",
        )
    docs.update_status(rfp_id, "drafting")
    celery_app.send_task("draft_proposal", args=[str(rfp_id)])
    return DocumentStatusResponse(
        rfp_id=str(rfp_id),
        file_name=document["file_name"],
        processing_status="drafting",
        requirements_count=requirements_count,
    )
