"""Persistence for RFP documents and their extracted requirements (Stories 2.2 / 2.5).

Owns all reads/writes against `rfp_documents` and `extracted_requirements`.
Kept dependency-free of FastAPI so both the API layer and the Celery worker can
call it.
"""

import logging
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from psycopg2.extras import Json

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


def update_solicitation_summary(rfp_id: UUID, summary: Optional[dict]) -> None:
    """Persists the document-level solicitation summary as JSONB.

    Supplementary to the compliance matrix — written best-effort by ingestion, so
    a null column simply means the summary stage was skipped or failed. Passing
    None writes SQL NULL, which lets a re-analysis clear a now-stale summary when
    its fresh extraction did not succeed.
    """
    value = Json(summary) if summary is not None else None
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE rfp_documents SET solicitation_summary = %s, updated_at = NOW() "
                "WHERE rfp_id = %s;",
                (value, str(rfp_id)),
            )
    finally:
        conn.close()
    logger.info(
        "%s solicitation summary for rfp_document %s",
        "Stored" if summary is not None else "Cleared",
        rfp_id,
    )


def get_solicitation_summary(rfp_id: UUID) -> Optional[dict]:
    """Returns the stored solicitation summary (JSONB → dict), or None if unset."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT solicitation_summary FROM rfp_documents WHERE rfp_id = %s;",
                (str(rfp_id),),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise DocumentNotFoundError(f"rfp_document {rfp_id} not found")
    return row[0]  # psycopg2 decodes JSONB to a dict (or None)


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


def get_requirements(rfp_id: UUID) -> list[dict]:
    """Returns the extracted compliance requirements for a document.

    Used by the drafting agent to plan and ground proposal sections. Ordered by
    creation so a positional reference index is stable within a single run.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT requirement_id, section_number, raw_text_content, category "
                "FROM extracted_requirements WHERE rfp_id = %s ORDER BY created_at;",
                (str(rfp_id),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "requirement_id": str(r[0]),
            "section_number": r[1],
            "raw_text_content": r[2],
            "category": r[3],
        }
        for r in rows
    ]


def insert_proposal_section(
    rfp_id: UUID,
    section_title: str,
    content: str,
    requirement_id: UUID | None = None,
    status: str = "needs_review",
    review_notes: str | None = None,
) -> UUID:
    """Inserts one drafted proposal section and returns its id.

    `requirement_id` is the *primary* requirement the section answers (the schema
    links one section → one requirement); a section may cover several, tracked in
    its content. A join table can normalise the many-to-many mapping later.

    `review_notes` carries the compliance critic's unresolved feedback for a
    section saved needs_review, so a reviewer can see what still needs attention.
    """
    section_id = uuid4()
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO proposal_sections
                    (section_id, rfp_id, requirement_id, section_title,
                     generated_draft_content, status, review_notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    str(section_id),
                    str(rfp_id),
                    str(requirement_id) if requirement_id else None,
                    section_title,
                    content,
                    status,
                    review_notes,
                ),
            )
    finally:
        conn.close()
    logger.info(
        "Inserted proposal_section %s (%s) for rfp_document %s", section_id, status, rfp_id
    )
    return section_id


def insert_requirements(rfp_id: UUID, matrix: "ComplianceMatrix") -> int:
    """Atomically replaces the document's extracted requirements. Returns rows written.

    Deletes any prior matrix and bulk-inserts the new one in a single
    transaction, so re-analyzing an RFP never appends a duplicate copy nor leaves
    a window with an empty matrix — if the insert fails, the delete rolls back
    with it. The delete runs even when the new matrix is empty, so a re-analysis
    that yields nothing clears the stale rows rather than keeping them.
    proposal_sections.requirement_id is ON DELETE SET NULL, so existing section
    links are simply cleared.
    """
    rows = [
        (str(rfp_id), r.section_number, r.raw_text_content, r.category)
        for r in matrix.requirements
    ]
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM extracted_requirements WHERE rfp_id = %s;",
                (str(rfp_id),),
            )
            deleted = cur.rowcount
            if rows:
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
    logger.info(
        "Replaced requirements for rfp_document %s: -%d +%d", rfp_id, deleted, len(rows)
    )
    return len(rows)
