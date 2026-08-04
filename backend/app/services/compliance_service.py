"""Compliance-matrix aggregation (Story: GET /proposals/{id}/compliance).

Real, DB-backed: reuses workspace_service.list_requirements (which enforces
tenant ownership) and rolls the requirement statuses up into the counts and
score the compliance grid renders. No new tables — this is a read-side view
over `extracted_requirements`.
"""

from uuid import UUID

from app.models.contract import ComplianceCounts, ComplianceMatrix, IntegrityItem
from app.services import workspace_service as ws

# The pre-export checklist, in display order. Kept as data so the "nothing yet"
# case (no linked RFP) returns the same items, all 'missing'.
_INTEGRITY_LABELS = [
    ("req-extracted", "Requirements extracted from the RFP"),
    ("req-addressed", "All requirements addressed"),
    ("sections-drafted", "All sections drafted"),
    ("sections-approved", "All sections approved"),
    ("compliance-score", "Compliance score at least 90%"),
]


def build_matrix(rfp_id: UUID, user_id: UUID, proposal_id: UUID | None = None) -> ComplianceMatrix:
    """Builds the matrix for `rfp_id`, reported against `proposal_id`.

    `proposal_id` is what the client addressed; it defaults to the rfp_id for
    callers that have no proposal in hand (the integrity check). Raises
    ws.NotFoundError if the rfp is missing or not owned by the tenant.
    """
    requirements = ws.list_requirements(rfp_id, user_id)

    counts = ComplianceCounts(
        all=len(requirements),
        addressed=sum(1 for r in requirements if r.compliance_status == "addressed"),
        partial=sum(1 for r in requirements if r.compliance_status == "partial"),
        missing=sum(1 for r in requirements if r.compliance_status == "missing"),
        na=sum(1 for r in requirements if r.compliance_status == "na"),
    )

    # Score = share of requirements fully addressed (partials count as half),
    # ignoring N/A rows. Empty matrix scores 0.
    scorable = counts.all - counts.na
    score = (
        round(100 * (counts.addressed + 0.5 * counts.partial) / scorable)
        if scorable > 0
        else 0
    )

    return ComplianceMatrix(
        proposal_id=str(proposal_id or rfp_id),
        compliance_score=score,
        counts=counts,
        requirements=requirements,
    )


def empty_integrity() -> list[IntegrityItem]:
    """Checklist for a proposal with no linked RFP yet — nothing verified."""
    return [IntegrityItem(id=cid, label=label, status="missing") for cid, label in _INTEGRITY_LABELS]


def build_integrity(rfp_id: UUID, proposal_id: UUID, user_id: UUID) -> list[IntegrityItem]:
    """Derives the pre-export checklist from the real matrix + sections.

    Takes both ids because the two halves are scoped differently: the compliance
    matrix belongs to the document (shared by every proposal on it), the drafted
    sections to this proposal alone.

    Raises ws.NotFoundError if either is missing or not owned by the tenant.
    """
    matrix = build_matrix(rfp_id, user_id)
    sections = ws.list_sections(proposal_id, user_id)
    c = matrix.counts

    if c.all == 0:
        req_addressed = "missing"
    elif c.missing > 0:
        req_addressed = "missing"
    elif c.partial > 0:
        req_addressed = "review_required"
    else:
        req_addressed = "verified"

    if not sections:
        drafted = "missing"
    elif any(not (s.content or "").strip() for s in sections):
        drafted = "review_required"
    else:
        drafted = "verified"

    if not sections:
        approved = "missing"
    elif all(s.status == "approved" for s in sections):
        approved = "verified"
    else:
        approved = "review_required"

    score = matrix.compliance_score
    score_status = "verified" if score >= 90 else ("review_required" if score >= 70 else "missing")

    statuses = {
        "req-extracted": "verified" if c.all > 0 else "missing",
        "req-addressed": req_addressed,
        "sections-drafted": drafted,
        "sections-approved": approved,
        "compliance-score": score_status,
    }
    return [IntegrityItem(id=cid, label=label, status=statuses[cid]) for cid, label in _INTEGRITY_LABELS]
