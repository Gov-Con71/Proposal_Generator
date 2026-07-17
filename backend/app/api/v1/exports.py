"""Export-job endpoints (Sprint 5/6).

    POST /exports                → create an export job for an owned proposal
    GET  /exports/{job_id}       → poll job status
    GET  /exports/{job_id}/download → stream the rendered artifact

Backed by export_service: jobs persist in `export_jobs`, rendering runs on the
Celery worker (render_export → real PDF/DOCX/XLSX/ZIP → S3). Tenant-scoped via
the JWT. The download route is what the frontend's `exportApi.download`
resolves the job's `downloadUrl` to.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from app.core.deps import get_current_user_id, require_writer
from app.models.contract import ExportCreateRequest, ExportJob
from app.services import export_service, proposals_service
from app.worker.celery_app import celery_app

router = APIRouter(prefix="/exports", tags=["Exports"])


@router.post("", response_model=ExportJob, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_writer)])
def create_export(
    payload: ExportCreateRequest, user_id: UUID = Depends(get_current_user_id)
) -> ExportJob:
    """Creates a 'pending' job and hands rendering off to the async worker.

    The client polls GET /exports/{id} until status is 'ready', then downloads.
    """
    # The export_jobs FK requires a proposal this tenant owns; reject early with
    # a clean 404 rather than letting the insert fail on the constraint.
    try:
        proposal_id = UUID(payload.proposal_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found.")
    if not proposals_service.exists_owned(proposal_id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found.")

    job = export_service.create_job(user_id, str(proposal_id), payload.format)
    celery_app.send_task("render_export", args=[job.id])
    return job


@router.get("/{job_id}", response_model=ExportJob)
def get_export(job_id: str, user_id: UUID = Depends(get_current_user_id)) -> ExportJob:
    job = export_service.get_job(user_id, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export job not found.")
    return job


@router.get("/{job_id}/download", summary="Download the rendered export artifact")
def download_export(job_id: str, user_id: UUID = Depends(get_current_user_id)) -> Response:
    artifact = export_service.render_artifact(user_id, job_id)
    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export not ready or not found.")
    payload, mime, filename = artifact
    return Response(
        content=payload,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
