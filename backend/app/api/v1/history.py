"""Historical past-performance ingestion endpoints (Story 3.1).

    POST /history  → chunk + embed + store past-performance text (tenant-scoped)
    GET  /history  → list ingested sources

Feeds the RAG retrieval used by the draft writer.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.core.deps import get_current_user_id, require_writer
from app.models.contract import HistoryIngestRequest, HistoryIngestResponse, HistorySource
from app.services import history_service as history

router = APIRouter(prefix="/history", tags=["History (RAG)"])


@router.post(
    "",
    response_model=HistoryIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest past-performance text into the vector store",
    dependencies=[Depends(require_writer)],
)
def ingest(
    payload: HistoryIngestRequest, user_id: UUID = Depends(get_current_user_id)
) -> HistoryIngestResponse:
    count = history.store_history(
        user_id,
        payload.source_name,
        payload.content,
        industry=payload.industry,
        document_type=payload.document_type,
        outcome=payload.outcome,
    )
    return HistoryIngestResponse(source_name=payload.source_name, chunks=count)


@router.get("", response_model=list[HistorySource], summary="List ingested history sources")
def sources(user_id: UUID = Depends(get_current_user_id)) -> list[HistorySource]:
    return [HistorySource(**s) for s in history.list_sources(user_id)]
