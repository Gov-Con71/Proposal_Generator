"""Persistence for RFP documents and their extracted requirements (Stories 2.2 / 2.5).

Owns all reads/writes against `rfp_documents` and `extracted_requirements`.
Kept dependency-free of FastAPI so both the API layer and the Celery worker can
call it.
"""

import logging
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from app.core.db import get_connection

if TYPE_CHECKING:  # keeps the LLM/langgraph stack out of the API import chain
    from app.services.compliance_extractor import ComplianceMatrix

logger = logging.getLogger(__name__)


class UnknownUploaderError(Exception):
    """Raised when the uploader is not a valid user (FK violation) — multi-tenant guard."""


class DocumentNotFoundError(Exception):
    """Raised when a referenced rfp_document row does not exist."""


def create_rfp_document(uploaded_by: UUID, file_name: str, s3_key: str) -> UUID:
    """Inserts a pending rfp_documents row and returns its id.

    The rfp_id is generated app-side so the caller can build the S3 key before
    the row exists (key embeds the id for tenant isolation).
    """
    rfp_id = uuid4()
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rfp_documents
                    (rfp_id, uploaded_by, file_name, s3_storage_key, processing_status)
                VALUES (%s, %s, %s, %s, 'pending');
                """,
                (str(rfp_id), str(uploaded_by), file_name, s3_key),
            )
    except Exception as exc:  # psycopg2.errors.ForeignKeyViolation and friends
        conn.rollback()
        if "foreign key" in str(exc).lower() or "rfp_documents_uploaded_by_fkey" in str(exc):
            raise UnknownUploaderError(str(exc)) from exc
        raise
    finally:
        conn.close()
    logger.info("Created rfp_document %s for uploader %s", rfp_id, uploaded_by)
    return rfp_id


def update_status(rfp_id: UUID, status: str) -> None:
    """Advances the processing_status of a document (pending/parsing/completed/failed)."""
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE rfp_documents SET processing_status = %s, updated_at = NOW() "
                "WHERE rfp_id = %s;",
                (status, str(rfp_id)),
            )
    finally:
        conn.close()


def get_document(rfp_id: UUID) -> dict:
    """Returns the rfp_document row as a dict, or raises DocumentNotFoundError."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rfp_id, uploaded_by, file_name, s3_storage_key, processing_status "
                "FROM rfp_documents WHERE rfp_id = %s;",
                (str(rfp_id),),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise DocumentNotFoundError(f"rfp_document {rfp_id} not found")
    return {
        "rfp_id": row[0],
        "uploaded_by": row[1],
        "file_name": row[2],
        "s3_storage_key": row[3],
        "processing_status": row[4],
    }


def count_requirements(rfp_id: UUID) -> int:
    """Returns how many extracted requirements exist for a document."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM extracted_requirements WHERE rfp_id = %s;",
                (str(rfp_id),),
            )
            (count,) = cur.fetchone()
    finally:
        conn.close()
    return count


def insert_requirements(rfp_id: UUID, matrix: "ComplianceMatrix") -> int:
    """Bulk-inserts extracted requirements for a document. Returns rows written."""
    if not matrix.requirements:
        return 0
    rows = [
        (str(rfp_id), r.section_number, r.raw_text_content, r.category)
        for r in matrix.requirements
    ]
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO extracted_requirements
                    (rfp_id, section_number, raw_text_content, category)
                VALUES (%s, %s, %s, %s);
                """,
                rows,
            )
    finally:
        conn.close()
    logger.info("Inserted %d requirements for rfp_document %s", len(rows), rfp_id)
    return len(rows)
