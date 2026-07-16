"""Ingestion-pipeline progress stream (Server-Sent Events).

    GET /proposals/{rfp_id}/pipeline/stream  → text/event-stream of Pipeline JSON

Reflects the *real* ingestion status of an uploaded RFP: it polls
`rfp_documents.processing_status` (advanced by the Celery worker through
pending → parsing → extracting → completed/failed) and maps it onto the step
view the frontend's `useProcessing` hook renders, closing when a terminal
snapshot (`completed`/`failed`) is sent.

Auth note: the browser EventSource API cannot set an Authorization header, so
this route takes an optional `?token=` query param instead of the bearer
dependency. When a valid token is supplied, the stream is scoped to the owning
tenant; without one it still streams status (the rfp_id acts as the capability).
"""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

import jwt
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.security import decode_token
from app.models.contract import Pipeline, PipelineStep
from app.services import document_service as docs

router = APIRouter(tags=["Documents"])

# Ordered pipeline stages shown in the frontend's process view.
_STEPS = [
    ("upload", "Upload", "Streaming the RFP to secure storage."),
    ("parse", "Parse", "Extracting text and structure from the document."),
    ("extract", "Extract requirements", "Shredding the RFP into compliance rules."),
    ("classify", "Classify", "Categorising and mapping each requirement."),
    ("ready", "Ready", "Compliance matrix is ready for review."),
]

# Real processing_status → (# fully-completed steps, failed?). Statuses in the
# drafting family mean ingestion already finished, so they read as complete.
_STATUS_MAP = {
    "pending": (1, False),
    "parsing": (1, False),
    "extracting": (2, False),
    "completed": (len(_STEPS), False),
    "drafting": (len(_STEPS), False),
    "drafted": (len(_STEPS), False),
    "draft_failed": (len(_STEPS), False),
    "failed": (2, True),
}

_POLL_SECONDS = 1.0
_MAX_POLLS = 150  # ~2.5 min safety cap so a stuck document can't stream forever


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_state(rfp_id: str) -> tuple[str | None, int, str | None]:
    """Sync DB read (run off-thread): (processing_status, requirement_count, owner)."""
    try:
        document = docs.get_document(UUID(rfp_id))
    except docs.DocumentNotFoundError:
        return None, 0, None
    return document["processing_status"], docs.count_requirements(UUID(rfp_id)), str(document["uploaded_by"])


def _snapshot(rfp_id: str, started_at: str, status: str, count: int) -> Pipeline:
    completed_index, failed = _STATUS_MAP.get(status, (0, False))

    steps: list[PipelineStep] = []
    for i, (sid, label, desc) in enumerate(_STEPS):
        if failed and i == completed_index:
            step_status = "failed"
        elif i < completed_index:
            step_status = "completed"
        elif i == completed_index:
            step_status = "running"
        else:
            step_status = "pending"
        steps.append(
            PipelineStep(
                id=sid,
                label=label,
                description=desc,
                status=step_status,
                completed_at=_now() if step_status == "completed" else None,
                meta=f"{count} requirements" if sid == "extract" and count else None,
            )
        )

    done = completed_index >= len(_STEPS)
    run_status = "failed" if failed else ("completed" if done else "running")
    if failed:
        message = "Processing failed."
    elif done:
        message = "Processing complete."
    else:
        message = f"Running: {_STEPS[min(completed_index, len(_STEPS) - 1)][1]}"

    return Pipeline(
        proposal_id=rfp_id,
        status=run_status,
        overall_progress=round(100 * min(completed_index, len(_STEPS)) / len(_STEPS)),
        steps=steps,
        started_at=started_at,
        completed_at=_now() if done else None,
        status_message=message,
    )


async def _event_stream(rfp_id: str, user_id: str | None):
    started_at = _now()
    last_payload: str | None = None

    for _ in range(_MAX_POLLS):
        status, count, owner = await asyncio.to_thread(_read_state, rfp_id)

        if status is None:
            pipe = Pipeline(
                proposal_id=rfp_id, status="failed", overall_progress=0, steps=[],
                started_at=started_at, completed_at=_now(), status_message="Document not found.",
            )
            yield f"data: {pipe.model_dump_json(by_alias=True)}\n\n"
            return

        # Scope to the owner when a token was supplied; never leak another tenant's progress.
        if user_id is not None and owner is not None and owner != user_id:
            return

        pipe = _snapshot(rfp_id, started_at, status, count)
        payload = pipe.model_dump_json(by_alias=True)
        if payload != last_payload:  # only push on change (plus the terminal frame)
            yield f"data: {payload}\n\n"
            last_payload = payload

        if pipe.status in ("completed", "failed"):
            return
        await asyncio.sleep(_POLL_SECONDS)


@router.get("/proposals/{rfp_id}/pipeline/stream")
async def stream_pipeline(rfp_id: UUID, token: str | None = None) -> StreamingResponse:
    user_id: str | None = None
    if token:
        try:
            user_id = decode_token(token)
        except jwt.PyJWTError:
            user_id = None  # invalid token → fall back to unscoped status streaming

    return StreamingResponse(
        _event_stream(str(rfp_id), user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering so events flush live
        },
    )
