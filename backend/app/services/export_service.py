"""Export-job orchestration (Sprint 5).

Jobs persist in `export_jobs`, tenant-scoped by `created_by`. The lifecycle
matches what the frontend's `exportApi` drives:

    create_job  → row at 'pending', enqueue render_export (by the router)
    render_export (Celery worker) → run_export_render:
        'generating' → assemble content → render bytes → upload to S3 → 'ready'
        (any failure → 'failed' with an error message)
    get_job     → poll status (tenant-scoped)
    render_artifact → stream the rendered S3 object back on download

Rendering (formats) lives in export_renderer; content assembly (DB reads) lives
here, so neither the router nor the renderer knows about the other.
"""

import io
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from psycopg2.extras import RealDictCursor

from app.core.db import get_connection
from app.models.contract import ExportJob
from app.services import (
    compliance_service,
    export_renderer,
    proposals_service,
    workspace_service as ws,
)
from app.services.export_renderer import ExportDoc
from app.services.s3_storage import S3Storage

logger = logging.getLogger(__name__)

_COLS = "job_id, proposal_id, format, status, download_url, created_at, expires_at"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_job(row: dict) -> ExportJob:
    return ExportJob(
        id=str(row["job_id"]),
        proposal_id=row["proposal_id"],
        format=row["format"],
        status=row["status"],
        download_url=row["download_url"],
        created_at=row["created_at"].isoformat() if row.get("created_at") else "",
        expires_at=row["expires_at"].isoformat() if row.get("expires_at") else None,
    )


def _execute(sql: str, params: tuple, *, fetch: bool = False):
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone() if fetch else None
    finally:
        conn.close()


# --- create / read (API surface) --------------------------------------------

def create_job(user_id: UUID, proposal_id: str, fmt: str) -> ExportJob:
    """Inserts a 'pending' job. The router enqueues render_export after this."""
    job_id = uuid4()
    expires_at = _now() + timedelta(hours=24)
    row = _execute(
        "INSERT INTO export_jobs "
        "(job_id, created_by, proposal_id, format, status, expires_at) "
        f"VALUES (%s, %s, %s, %s, 'pending', %s) RETURNING {_COLS};",
        (str(job_id), str(user_id), proposal_id, fmt, expires_at),
        fetch=True,
    )
    logger.info("create_job: export %s (%s) queued for tenant %s", job_id, fmt, user_id)
    return _to_job(row)


def get_job(user_id: UUID, job_id: str) -> ExportJob | None:
    """Returns the job if it exists and belongs to the tenant, else None."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {_COLS} FROM export_jobs WHERE job_id = %s AND created_by = %s;",
                (job_id, str(user_id)),
            )
            row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001 — malformed (non-UUID) job_id → treat as missing
        logger.debug("get_job lookup failed for %s: %s", job_id, exc)
        return None
    finally:
        conn.close()
    return _to_job(row) if row else None


# --- worker: render pipeline ------------------------------------------------

def _mark(job_id: str, status: str, **extra) -> None:
    """Updates a job's status (+ optional download_url/s3_key/error) by id."""
    sets, vals = ["status = %s"], [status]
    for col in ("download_url", "s3_key", "error"):
        if col in extra:
            sets.append(f"{col} = %s")
            vals.append(extra[col])
    _execute(
        f"UPDATE export_jobs SET {', '.join(sets)} WHERE job_id = %s;",
        (*vals, job_id),
    )


def _assemble_doc(created_by: UUID, proposal_id: str) -> ExportDoc:
    """Builds the export payload from the proposal's sections + compliance matrix.

    proposal_id references proposals(proposal_id) (enforced by the FK). We resolve
    the proposal to its linked RFP and pull that RFP's sections + compliance
    matrix; an unlinked proposal still renders a valid document noting there is
    no content yet.
    """
    try:
        proposal = proposals_service.get_proposal(UUID(proposal_id), created_by)
    except (ValueError, proposals_service.NotFoundError):
        return ExportDoc(title=f"Proposal Export — {proposal_id}", subtitle="Proposal not found.")

    title = proposal.title or f"Proposal Export — {proposal_id}"
    if not proposal.document_id:  # documentId == the linked rfp_id
        return ExportDoc(title=title, subtitle="No RFP linked to this proposal yet.")

    try:
        rfp_id = UUID(proposal.document_id)
        sections = ws.list_sections(rfp_id, created_by)
        matrix = compliance_service.build_matrix(rfp_id, created_by)
    except (ValueError, ws.NotFoundError):
        return ExportDoc(title=title, subtitle="No proposal content found for this tenant.")

    return ExportDoc(
        title=title,
        subtitle=f"Compliance score: {matrix.compliance_score}% · {matrix.counts.all} requirements",
        sections=[{"title": s.title, "content": s.content} for s in sections],
        requirements=[
            {"number": r.number, "section": r.section, "status": r.compliance_status, "text": r.text}
            for r in matrix.requirements
        ],
    )


def run_export_render(job_id: str) -> dict:
    """Worker entry point: render a job's artifact to S3 and mark it ready.

    Flips the row to 'failed' (with the error) before re-raising so the Celery
    task can record/retry the failure — mirroring the ingestion pipeline.
    """
    row = _execute(
        "SELECT created_by, proposal_id, format FROM export_jobs WHERE job_id = %s;",
        (job_id,),
        fetch=True,
    )
    if row is None:
        raise ValueError(f"export job {job_id} not found")

    created_by, proposal_id, fmt = row["created_by"], row["proposal_id"], row["format"]
    try:
        _mark(job_id, "generating")
        doc = _assemble_doc(created_by, proposal_id)
        payload, mime = export_renderer.render(fmt, doc)

        s3_key = f"exports/{created_by}/{job_id}/proposal-{proposal_id}.{fmt}"
        S3Storage().stream_upload(s3_key, io.BytesIO(payload), mime)

        _mark(job_id, "ready", s3_key=s3_key, download_url=f"/exports/{job_id}/download", error=None)
        logger.info("run_export_render: job %s ready (%d bytes → %s)", job_id, len(payload), s3_key)
        return {"job_id": job_id, "status": "ready", "bytes": len(payload)}
    except Exception as exc:
        _mark(job_id, "failed", error=str(exc))
        logger.exception("run_export_render failed for job %s", job_id)
        raise


# --- download ---------------------------------------------------------------

def render_artifact(user_id: UUID, job_id: str) -> tuple[bytes, str, str] | None:
    """Returns (bytes, mime_type, filename) for a ready job, else None.

    Streams the artifact the worker rendered to S3. None → 404 at the router
    (job missing, not owned, not ready, or artifact unavailable).
    """
    job = get_job(user_id, job_id)
    if job is None or job.status != "ready":
        return None

    row = _execute(
        "SELECT s3_key FROM export_jobs WHERE job_id = %s AND created_by = %s;",
        (job_id, str(user_id)),
        fetch=True,
    )
    s3_key = row["s3_key"] if row else None
    if not s3_key:
        return None

    try:
        payload = S3Storage().download_bytes(s3_key)
    except Exception as exc:  # noqa: BLE001 — missing/unreadable object → 404
        logger.warning("render_artifact: could not fetch %s: %s", s3_key, exc)
        return None

    filename = f"proposal-{job.proposal_id}.{job.format}"
    return payload, export_renderer.MIME.get(job.format, "application/octet-stream"), filename
