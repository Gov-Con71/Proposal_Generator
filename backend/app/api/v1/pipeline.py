"""Ingestion-pipeline progress stream (Server-Sent Events).

    GET /proposals/{proposal_id}/pipeline/stream  → text/event-stream of Pipeline JSON

Reflects the *real* ingestion status of an uploaded RFP: it polls
`rfp_documents.processing_status` (advanced by the Celery worker through
pending → parsing → extracting → completed/failed) and maps it onto the step
view the frontend's `useProcessing` hook renders, closing when a terminal
snapshot (`completed`/`failed`) is sent.

Auth note: the browser EventSource API cannot set an Authorization header, so
the stream is authorised by a **ticket** obtained from a normal, bearer-
authenticated POST:

    POST /proposals/{id}/pipeline/ticket   → {"ticket": "..."}   (Authorization)
    GET  /proposals/{id}/pipeline/stream?ticket=...              (no header)

The ticket is single-use, expires in seconds, and authorises only this one
proposal's stream — see `stream_ticket_service`. It replaces `?token=`, which
put a full-privilege 15-minute access token into access logs, browser history
and Referer headers (GAP_ANALYSIS.md §2.2).
"""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.deps import get_current_user_id
from app.models.contract import CamelModel, Pipeline, PipelineStep
from app.services import document_service as docs
from app.services import proposals_service
from app.services import stream_ticket_service as tickets

router = APIRouter(tags=["Documents"])

# Ordered pipeline stages shown in the frontend's process view.
_STEPS = [
    ("upload", "Upload", "Streaming the RFP to secure storage."),
    ("parse", "Parse", "Extracting text and structure from the document."),
    ("extract", "Extract requirements", "Shredding the RFP into compliance rules."),
    ("classify", "Classify", "Categorising and mapping each requirement."),
    ("ready", "Ready", "Compliance matrix is ready for review."),
]

# Real processing_status → (# fully-completed steps, failed?).
#
# The drafting states ('drafting'/'drafted'/'draft_failed') used to appear here,
# mapped to "ingestion complete", because the document carried both lifecycles.
# Migration 0005 moved drafting onto the proposal, so this column describes only
# how far ingestion got. An unrecognised status still falls through to (0, False)
# via `.get`, which is the right answer for a state this view knows nothing about.
_STATUS_MAP = {
    "pending": (1, False),
    "parsing": (1, False),
    "extracting": (2, False),
    "completed": (len(_STEPS), False),
    "failed": (2, True),
}

_POLL_SECONDS = 1.0
# ~10 min. The old 2.5 min cap was shorter than a real ingestion: a throttled
# provider (429 backoff) plus a single multi-minute extraction call routinely
# runs 3-5 min, so the stream died *before* the work finished and the client
# reported a lost connection for a run that went on to succeed.
_MAX_POLLS = 600
# Sent on every poll that produces no state change. Without bytes on the wire a
# proxy (or a laptop suspending its sockets) idles the connection out during the
# long extraction step, which reads to the client as a dropped stream.
_HEARTBEAT = ": ping\n\n"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_state(rfp_id: str) -> tuple[str | None, int, str | None]:
    """Sync DB read (run off-thread): (processing_status, requirement_count, owner)."""
    try:
        document = docs.get_document(UUID(rfp_id))
    except docs.DocumentNotFoundError:
        return None, 0, None
    return document["processing_status"], docs.count_requirements(UUID(rfp_id)), str(document["uploaded_by"])


def _snapshot(
    proposal_id: str,
    started_at: str,
    doc_status: str,
    count: int,
    step_completed_at: dict[str, str],
) -> Pipeline:
    """Builds the frame the client sees. `proposal_id` is what it addressed; the
    status behind it was read from the linked document.

    `step_completed_at` carries each step's first-seen completion time across
    polls and is filled in as steps finish. Stamping `_now()` on every poll
    instead made each completed step's timestamp jitter by a second and left no
    two snapshots ever equal, which defeated the caller's change detection."""
    completed_index, failed = _STATUS_MAP.get(doc_status, (0, False))

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
                completed_at=(
                    step_completed_at.setdefault(sid, _now())
                    if step_status == "completed"
                    else None
                ),
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
        proposal_id=proposal_id,
        status=run_status,
        overall_progress=round(100 * min(completed_index, len(_STEPS)) / len(_STEPS)),
        steps=steps,
        started_at=started_at,
        completed_at=_now() if done else None,
        status_message=message,
    )


async def _event_stream(rfp_id: str, proposal_id: str, user_id: str):
    """Reads progress by `rfp_id`; reports it against the `proposal_id` the
    client addressed, so the frame echoes the id it asked about."""
    started_at = _now()
    last_payload: str | None = None
    last_pipe: Pipeline | None = None
    step_completed_at: dict[str, str] = {}

    for _ in range(_MAX_POLLS):
        doc_status, count, owner = await asyncio.to_thread(_read_state, rfp_id)

        # A document this tenant doesn't own is reported exactly like a missing
        # one — the caller must not be able to tell the difference, or the
        # stream becomes an existence oracle for other tenants' rfp_ids.
        if doc_status is None or owner != user_id:
            pipe = Pipeline(
                proposal_id=proposal_id, status="failed", overall_progress=0, steps=[],
                started_at=started_at, completed_at=_now(), status_message="Document not found.",
            )
            yield f"data: {pipe.model_dump_json(by_alias=True)}\n\n"
            return

        last_pipe = _snapshot(proposal_id, started_at, doc_status, count, step_completed_at)
        payload = last_pipe.model_dump_json(by_alias=True)
        if payload != last_payload:  # only push on change (plus the terminal frame)
            yield f"data: {payload}\n\n"
            last_payload = payload
        else:
            yield _HEARTBEAT

        if last_pipe.status in ("completed", "failed"):
            return
        await asyncio.sleep(_POLL_SECONDS)

    # Budget exhausted with the document still working. Say so explicitly: a
    # silent `return` here closed the response with no explanation, leaving the
    # client unable to tell a still-running ingestion from a crashed server.
    # The run status stays "running" because that is the truth — only this
    # connection is giving up, not the ingestion.
    if last_pipe is not None:
        timed_out = last_pipe.model_copy(
            update={
                "status_message": (
                    "Still processing — this is taking longer than usual. "
                    "Progress is preserved; the workspace will show the result when it lands."
                )
            }
        )
        yield f"data: {timed_out.model_dump_json(by_alias=True)}\n\n"


class StreamTicketResponse(CamelModel):
    ticket: str
    expires_in_seconds: int


@router.post(
    "/proposals/{proposal_id}/pipeline/ticket",
    response_model=StreamTicketResponse,
    summary="Mint a single-use ticket for the progress stream",
)
async def issue_stream_ticket(
    proposal_id: UUID, user_id: UUID = Depends(get_current_user_id)
) -> StreamTicketResponse:
    """Exchanges a normal bearer credential for one scoped to this stream.

    Ownership is checked *here*, on the authenticated request, so the ticket
    itself never needs to carry authority beyond "the holder already proved they
    own this proposal, seconds ago".
    """
    try:
        await asyncio.to_thread(
            proposals_service.rfp_for_proposal, proposal_id, user_id
        )
    except proposals_service.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc
    except proposals_service.NoLinkedDocumentError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This proposal has no ingested RFP yet."
        ) from exc

    try:
        ticket = await asyncio.to_thread(tickets.issue, user_id, proposal_id)
    except tickets.TicketError as exc:
        # 503, not 500: the request was valid and the dependency is down. Unlike
        # the cache, this cannot fall back to "allow" — see the service docstring.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Progress streaming is temporarily unavailable.",
        ) from exc

    return StreamTicketResponse(
        ticket=ticket, expires_in_seconds=settings.stream_ticket_ttl_seconds
    )


@router.get("/proposals/{proposal_id}/pipeline/stream")
async def stream_pipeline(proposal_id: UUID, ticket: str | None = None) -> StreamingResponse:
    # A missing or bad ticket is a 401, exactly as on every sibling route. This
    # once fell back to unscoped streaming, which meant presenting no credential
    # granted *more* access than presenting another tenant's valid one.
    if not ticket:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "A ticket query parameter is required for this stream.",
        )
    try:
        # Redeeming is single-use and checks the ticket was issued for *this*
        # proposal, so a ticket recovered from a log or history is already spent.
        user_id = await asyncio.to_thread(tickets.redeem, ticket, proposal_id)
    except tickets.TicketError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid, expired, or already-used ticket."
        ) from exc

    # Resolve before streaming so an unknown proposal is a plain HTTP error the
    # client can act on, rather than a 200 stream carrying a failure frame.
    # Off-thread: rfp_for_proposal is a blocking DB call.
    try:
        rfp_id = await asyncio.to_thread(
            proposals_service.rfp_for_proposal, proposal_id, UUID(user_id)
        )
    except proposals_service.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc
    except proposals_service.NoLinkedDocumentError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This proposal has no ingested RFP yet.",
        ) from exc

    return StreamingResponse(
        _event_stream(str(rfp_id), str(proposal_id), user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering so events flush live
        },
    )
