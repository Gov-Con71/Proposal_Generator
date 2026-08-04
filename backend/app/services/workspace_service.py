"""Requirement + proposal-section persistence for the workspace (Story 3.4).

Reads the real `extracted_requirements` produced by Sprint 2 ingestion and the
editable `proposal_sections`, mapping DB rows to the frontend contract shapes.

Ownership is resolved differently for the two, because they are scoped
differently: requirements are properties of the *document* (two proposals
answering one RFP share them, by design) and resolve through
`rfp_documents.uploaded_by`; sections are work product belonging to a single
*proposal* and resolve through `proposals.owned_by`.
"""

import logging
from uuid import UUID

from psycopg2.extras import Json, RealDictCursor

from app.core.db import get_connection
from app.models.contract import ProposalSection, Requirement

logger = logging.getLogger(__name__)


class NotFoundError(Exception):
    """Row missing (or not owned by the tenant — treated identically)."""


# --- vocabulary mapping (DB ↔ frontend enums) -------------------------------

_FRONT_STATUSES = {"addressed", "partial", "missing", "na"}
_DB_STATUS_MAP = {"pending": "missing", "compliant": "addressed", "exception": "partial"}
_CATEGORY_MAP = {
    "technical": "technical",
    "security": "security",
    "past performance": "compliance",
    # Sections L and M. The frontend vocabulary has no dedicated term for either,
    # so they map to their nearest sense — without these they would fall through
    # to the "technical" default and read to a reviewer as work to perform rather
    # than as rules governing the proposal.
    "instruction": "admin",
    "evaluation criteria": "compliance",
}
_VALID_CATEGORIES = {
    "scope", "technical", "testing", "quality_assurance", "packaging", "marking",
    "financial", "legal", "compliance", "personnel", "reporting", "security",
    "service_level", "admin",
}


def _map_status(raw: str | None) -> str:
    if raw in _FRONT_STATUSES:
        return raw
    return _DB_STATUS_MAP.get((raw or "").lower(), "missing")


def _map_category(raw: str | None) -> str:
    low = (raw or "").lower()
    if low in _VALID_CATEGORIES:
        return low
    return _CATEGORY_MAP.get(low, "technical")


# --- ownership --------------------------------------------------------------

def _fetchone(sql: str, params: tuple) -> dict | None:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


def assert_rfp_owner(rfp_id: UUID, user_id: UUID) -> None:
    row = _fetchone("SELECT uploaded_by FROM rfp_documents WHERE rfp_id = %s;", (str(rfp_id),))
    if row is None or str(row["uploaded_by"]) != str(user_id):
        raise NotFoundError(f"rfp {rfp_id}")


def assert_proposal_owner(proposal_id: UUID, user_id: UUID) -> None:
    """Sections are proposal-scoped, so their tenancy comes from the proposal
    rather than from the document behind it."""
    row = _fetchone(
        "SELECT owned_by FROM proposals WHERE proposal_id = %s;", (str(proposal_id),)
    )
    if row is None or str(row["owned_by"]) != str(user_id):
        raise NotFoundError(f"proposal {proposal_id}")


# --- requirements -----------------------------------------------------------

def _to_requirement(row: dict, number: int) -> Requirement:
    return Requirement(
        id=str(row["requirement_id"]),
        document_id=str(row["rfp_id"]),
        number=number,
        section=row.get("section_number") or "",
        text=row["raw_text_content"],
        category=_map_category(row.get("category")),
        type="mandatory",
        compliance_status=_map_status(row.get("compliance_status")),
        confidence_score=None,
        proposal_section_id=None,
        proposal_section_title=None,
        created_at=row["created_at"].isoformat() if row.get("created_at") else "",
    )


def list_requirements(rfp_id: UUID, user_id: UUID) -> list[Requirement]:
    assert_rfp_owner(rfp_id, user_id)
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT requirement_id, rfp_id, section_number, raw_text_content, "
                "category, compliance_status, created_at "
                "FROM extracted_requirements WHERE rfp_id = %s ORDER BY created_at;",
                (str(rfp_id),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_to_requirement(r, i + 1) for i, r in enumerate(rows)]


def update_requirement(requirement_id: UUID, user_id: UUID, patch) -> Requirement:
    """Applies a partial update (status/category/text) after an ownership check."""
    row = _fetchone(
        "SELECT r.rfp_id, d.uploaded_by FROM extracted_requirements r "
        "JOIN rfp_documents d ON d.rfp_id = r.rfp_id WHERE r.requirement_id = %s;",
        (str(requirement_id),),
    )
    if row is None or str(row["uploaded_by"]) != str(user_id):
        raise NotFoundError(f"requirement {requirement_id}")

    fields, values = [], []
    if patch.compliance_status is not None:
        fields.append("compliance_status = %s")
        values.append(patch.compliance_status)
    if patch.category is not None:
        fields.append("category = %s")
        values.append(patch.category)
    if patch.text is not None:
        fields.append("raw_text_content = %s")
        values.append(patch.text)

    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            if fields:
                cur.execute(
                    f"UPDATE extracted_requirements SET {', '.join(fields)}, updated_at = NOW() "
                    "WHERE requirement_id = %s;",
                    (*values, str(requirement_id)),
                )
            cur.execute(
                "SELECT requirement_id, rfp_id, section_number, raw_text_content, "
                "category, compliance_status, created_at "
                "FROM extracted_requirements WHERE requirement_id = %s;",
                (str(requirement_id),),
            )
            updated = cur.fetchone()
            # number = position by creation order within the proposal
            cur.execute(
                "SELECT COUNT(*) AS n FROM extracted_requirements "
                "WHERE rfp_id = %s AND created_at <= %s;",
                (str(updated["rfp_id"]), updated["created_at"]),
            )
            number = cur.fetchone()["n"]
    finally:
        conn.close()
    return _to_requirement(updated, number)


def delete_requirement(requirement_id: UUID, user_id: UUID) -> UUID:
    """Deletes a requirement after an ownership check. Returns its rfp_id."""
    row = _fetchone(
        "SELECT r.rfp_id, d.uploaded_by FROM extracted_requirements r "
        "JOIN rfp_documents d ON d.rfp_id = r.rfp_id WHERE r.requirement_id = %s;",
        (str(requirement_id),),
    )
    if row is None or str(row["uploaded_by"]) != str(user_id):
        raise NotFoundError(f"requirement {requirement_id}")
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM extracted_requirements WHERE requirement_id = %s;",
                (str(requirement_id),),
            )
    finally:
        conn.close()
    return row["rfp_id"]


# --- sections ---------------------------------------------------------------

def _to_section(row: dict) -> ProposalSection:
    content = row.get("generated_draft_content") or ""
    status = row.get("status") or ("empty" if not content else "draft")
    return ProposalSection(
        id=str(row["section_id"]),
        proposal_id=str(row["proposal_id"]),
        title=row["section_title"],
        content=content,
        status=status,
        word_count=len(content.split()),
        # Real retrieval grounding since migration 0007; both were hardcoded
        # 0.0/[] before it, so the workspace's confidence and citation UI had
        # nothing to render. A section written by hand legitimately has neither.
        ai_confidence_score=float(row.get("ai_confidence_score") or 0.0),
        ai_flags=[],
        mapped_requirement_ids=[str(row["requirement_id"])] if row.get("requirement_id") else [],
        reference_tags=row.get("reference_tags") or [],
        review_notes=row.get("review_notes"),
        last_edited_at=row["updated_at"].isoformat() if row.get("updated_at") else "",
        last_edited_by="",
    )


_SECTION_COLS = (
    "section_id, proposal_id, requirement_id, section_title, generated_draft_content, "
    "status, review_notes, ai_confidence_score, reference_tags, created_at, updated_at"
)


def list_sections(proposal_id: UUID, user_id: UUID) -> list[ProposalSection]:
    assert_proposal_owner(proposal_id, user_id)
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {_SECTION_COLS} FROM proposal_sections "
                "WHERE proposal_id = %s ORDER BY created_at;",
                (str(proposal_id),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_to_section(r) for r in rows]


def _section_row(section_id: UUID, user_id: UUID) -> dict:
    # Ownership comes from the owning proposal. It used to be read from the
    # document (`rfp_documents.uploaded_by`), which gave every proposal built on
    # one RFP the same answer.
    row = _fetchone(
        "SELECT s.section_id, s.proposal_id, s.requirement_id, s.section_title, "
        "s.generated_draft_content, s.status, s.review_notes, s.created_at, s.updated_at, "
        "p.owned_by "
        "FROM proposal_sections s JOIN proposals p ON p.proposal_id = s.proposal_id "
        "WHERE s.section_id = %s;",
        (str(section_id),),
    )
    if row is None or str(row["owned_by"]) != str(user_id):
        raise NotFoundError(f"section {section_id}")
    return row


def get_section(section_id: UUID, user_id: UUID) -> ProposalSection:
    return _to_section(_section_row(section_id, user_id))


def create_section(
    proposal_id: UUID, user_id: UUID, title: str, requirement_id: str | None
) -> ProposalSection:
    assert_proposal_owner(proposal_id, user_id)
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO proposal_sections (proposal_id, requirement_id, section_title, status) "
                f"VALUES (%s, %s, %s, 'empty') RETURNING {_SECTION_COLS};",
                (str(proposal_id), requirement_id, title),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return _to_section(row)


def update_section(section_id: UUID, user_id: UUID, content: str | None, status: str | None) -> ProposalSection:
    _section_row(section_id, user_id)  # ownership check
    fields, values = [], []
    if content is not None:
        fields.append("generated_draft_content = %s")
        values.append(content)
    if status is not None:
        fields.append("status = %s")
        values.append(status)
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            if fields:
                cur.execute(
                    f"UPDATE proposal_sections SET {', '.join(fields)}, updated_at = NOW() "
                    "WHERE section_id = %s;",
                    (*values, str(section_id)),
                )
            cur.execute(
                f"SELECT {_SECTION_COLS} FROM proposal_sections WHERE section_id = %s;",
                (str(section_id),),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return _to_section(row)


def save_generated_draft(
    section_id: UUID,
    content: str,
    confidence: float = 0.0,
    reference_tags: list[str] | None = None,
) -> ProposalSection:
    """Writes a freshly generated draft to a section (ownership already checked).

    The grounding is overwritten, not merged: it describes *this* generation, so
    a regenerate that retrieved nothing must clear the previous run's citations
    rather than leave them attached to prose they no longer support.
    """
    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "UPDATE proposal_sections SET generated_draft_content = %s, status = 'draft', "
                "ai_confidence_score = %s, reference_tags = %s, "
                f"updated_at = NOW() WHERE section_id = %s RETURNING {_SECTION_COLS};",
                (content, confidence, Json(reference_tags or []), str(section_id)),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return _to_section(row)


def requirement_text_for_section(section_id: UUID) -> str:
    """Returns the mapped requirement's text (or the section title as a fallback)."""
    row = _fetchone(
        "SELECT s.section_title, r.raw_text_content FROM proposal_sections s "
        "LEFT JOIN extracted_requirements r ON r.requirement_id = s.requirement_id "
        "WHERE s.section_id = %s;",
        (str(section_id),),
    )
    if row is None:
        raise NotFoundError(f"section {section_id}")
    return row["raw_text_content"] or row["section_title"]
