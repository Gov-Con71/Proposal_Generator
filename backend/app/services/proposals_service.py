"""Proposal persistence (Sprint 6).

Real, DB-backed CRUD for the `proposals` table, replacing the Story 1.3 mock
router. Every operation is tenant-scoped by `owned_by`. A proposal may link to
an ingested RFP (`rfp_id`); when it does, its compliance score + requirement
counts are derived live from `extracted_requirements` rather than stored, so
the proposal view always agrees with the compliance grid.

The frontend contract exposes the link as `documentId` (== the rfp_id); the
column is `rfp_id`. Linking is validated against `rfp_documents` ownership so a
tenant can never attach (and read counts from) another tenant's RFP.
"""

import logging
from uuid import UUID

from psycopg2.extras import RealDictCursor

from app.core.db import get_connection
from app.models.contract import Proposal, ProposalCreate, ProposalSummary, ProposalUpdate
from app.services import workspace_service as ws

logger = logging.getLogger(__name__)


class NotFoundError(Exception):
    """Proposal missing, or not owned by the tenant (treated identically)."""


class InvalidLinkError(Exception):
    """documentId does not reference an RFP the tenant owns."""


# Columns writable from the API payloads (contract field -> column is 1:1 here,
# except documentId which maps to rfp_id and is handled separately).
_WRITABLE = {
    "title", "solicitation_number", "agency", "due_date", "status",
    "contract_type", "naics_code", "naics_description", "pricing_model",
    "target_profit_margin", "drafting_level", "tone", "page_limit",
}

_COLS = (
    "proposal_id, owned_by, rfp_id, title, solicitation_number, agency, due_date, "
    "compliance_score, status, contract_type, naics_code, naics_description, "
    "pricing_model, target_profit_margin, drafting_level, tone, page_limit, "
    "created_at, updated_at"
)


def _fetchone(sql: str, params: tuple) -> dict | None:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


# --- linking / ownership ----------------------------------------------------

def _resolve_rfp_link(document_id: str | None, user_id: UUID) -> UUID | None:
    """Validates documentId points to an RFP this tenant owns; returns its UUID."""
    if not document_id:
        return None
    try:
        rfp_id = UUID(document_id)
    except ValueError as exc:
        raise InvalidLinkError(f"documentId '{document_id}' is not a valid id.") from exc
    row = _fetchone("SELECT uploaded_by FROM rfp_documents WHERE rfp_id = %s;", (str(rfp_id),))
    if row is None or str(row["uploaded_by"]) != str(user_id):
        raise InvalidLinkError(f"RFP '{document_id}' not found for this tenant.")
    return rfp_id


# --- derived compliance -----------------------------------------------------

def _derive_counts(rfp_id: UUID | None) -> dict:
    """Rolls up requirement statuses for a linked RFP (zeros when unlinked)."""
    empty = {"score": 0, "total": 0, "addressed": 0, "partial": 0, "missing": 0}
    if rfp_id is None:
        return empty
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT compliance_status FROM extracted_requirements WHERE rfp_id = %s;",
                (str(rfp_id),),
            )
            statuses = [ws._map_status(r[0]) for r in cur.fetchall()]
    finally:
        conn.close()
    total = len(statuses)
    addressed = statuses.count("addressed")
    partial = statuses.count("partial")
    missing = statuses.count("missing")
    na = statuses.count("na")
    scorable = total - na
    score = round(100 * (addressed + 0.5 * partial) / scorable) if scorable > 0 else 0
    return {"score": score, "total": total, "addressed": addressed, "partial": partial, "missing": missing}


# --- row -> contract --------------------------------------------------------

def _to_summary(row: dict, counts: dict) -> ProposalSummary:
    return ProposalSummary(
        id=str(row["proposal_id"]),
        title=row["title"],
        solicitation_number=row["solicitation_number"],
        agency=row["agency"],
        due_date=row["due_date"],
        compliance_score=counts["score"],
        status=row["status"],
        created_at=row["created_at"].isoformat() if row.get("created_at") else "",
        updated_at=row["updated_at"].isoformat() if row.get("updated_at") else "",
    )


def _to_proposal(row: dict, counts: dict) -> Proposal:
    return Proposal(
        **_to_summary(row, counts).model_dump(),
        contract_type=row["contract_type"],
        naics_code=row["naics_code"],
        naics_description=row["naics_description"],
        pricing_model=row["pricing_model"],
        target_profit_margin=float(row["target_profit_margin"]),
        drafting_level=row["drafting_level"],
        tone=row["tone"],
        page_limit=row["page_limit"],
        document_id=str(row["rfp_id"]) if row.get("rfp_id") else "",
        total_requirements=counts["total"],
        addressed_requirements=counts["addressed"],
        partial_requirements=counts["partial"],
        missing_requirements=counts["missing"],
    )


# --- CRUD -------------------------------------------------------------------

def list_proposals(user_id: UUID) -> list[ProposalSummary]:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT {_COLS} FROM proposals WHERE owned_by = %s ORDER BY updated_at DESC;",
                (str(user_id),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_to_summary(r, _derive_counts(r["rfp_id"])) for r in rows]


def _owned_row(proposal_id: UUID, user_id: UUID) -> dict:
    row = _fetchone(
        f"SELECT {_COLS} FROM proposals WHERE proposal_id = %s AND owned_by = %s;",
        (str(proposal_id), str(user_id)),
    )
    if row is None:
        raise NotFoundError(f"proposal {proposal_id}")
    return row


def get_proposal(proposal_id: UUID, user_id: UUID) -> Proposal:
    row = _owned_row(proposal_id, user_id)
    return _to_proposal(row, _derive_counts(row["rfp_id"]))


def exists_owned(proposal_id: UUID, user_id: UUID) -> bool:
    return _fetchone(
        "SELECT 1 FROM proposals WHERE proposal_id = %s AND owned_by = %s;",
        (str(proposal_id), str(user_id)),
    ) is not None


def create_proposal(user_id: UUID, payload: ProposalCreate) -> Proposal:
    data = payload.model_dump(exclude_none=True)
    rfp_id = _resolve_rfp_link(data.pop("document_id", None), user_id)
    fields = {k: v for k, v in data.items() if k in _WRITABLE}

    cols = ["owned_by", "rfp_id", *fields.keys()]
    placeholders = ", ".join(["%s"] * len(cols))
    values = [str(user_id), str(rfp_id) if rfp_id else None, *fields.values()]

    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"INSERT INTO proposals ({', '.join(cols)}) VALUES ({placeholders}) RETURNING {_COLS};",
                values,
            )
            row = cur.fetchone()
    finally:
        conn.close()
    logger.info("create_proposal: %s for tenant %s", row["proposal_id"], user_id)
    return _to_proposal(row, _derive_counts(row["rfp_id"]))


def update_proposal(proposal_id: UUID, user_id: UUID, payload: ProposalUpdate) -> Proposal:
    _owned_row(proposal_id, user_id)  # ownership check
    data = payload.model_dump(exclude_none=True)

    sets, values = [], []
    if "document_id" in data:
        rfp_id = _resolve_rfp_link(data.pop("document_id"), user_id)
        sets.append("rfp_id = %s")
        values.append(str(rfp_id) if rfp_id else None)
    for key, val in data.items():
        if key in _WRITABLE:
            sets.append(f"{key} = %s")
            values.append(val)

    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            if sets:
                cur.execute(
                    f"UPDATE proposals SET {', '.join(sets)}, updated_at = NOW() "
                    "WHERE proposal_id = %s;",
                    (*values, str(proposal_id)),
                )
            cur.execute(f"SELECT {_COLS} FROM proposals WHERE proposal_id = %s;", (str(proposal_id),))
            row = cur.fetchone()
    finally:
        conn.close()
    return _to_proposal(row, _derive_counts(row["rfp_id"]))


def delete_proposal(proposal_id: UUID, user_id: UUID) -> None:
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM proposals WHERE proposal_id = %s AND owned_by = %s;",
                (str(proposal_id), str(user_id)),
            )
            if cur.rowcount == 0:
                raise NotFoundError(f"proposal {proposal_id}")
    finally:
        conn.close()
