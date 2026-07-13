"""Deterministic mock fixtures backing the Story 1.3 contract endpoints.

Kept in sync with `proposalai-frontend/lib/constants/mock-data.ts` so a
front-end developer sees identical shapes whether they hit the live mock API or
the local TypeScript fixtures.
"""

from app.models.contract import (
    AIFlag,
    Proposal,
    ProposalSection,
    ProposalSummary,
    Requirement,
    Session,
    User,
)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

MOCK_USER = User(
    id="u1",
    email="analyst@govcon.example",
    name="Jordan Sparks",
    role="analyst",
    company_id="c1",
    avatar_url=None,
    created_at="2026-01-04T09:00:00Z",
)


def mock_session() -> Session:
    """A fresh session envelope; tokens are obviously fake mock strings."""
    return Session(
        user=MOCK_USER,
        access_token="mock-access-token.jwt.signature",
        refresh_token="mock-refresh-token.jwt.signature",
        expires_at="2026-12-31T23:59:59Z",
    )


# ---------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------

MOCK_PROPOSAL_SUMMARIES: list[ProposalSummary] = [
    ProposalSummary(
        id="1",
        title="Centrifugal Pump Overhaul",
        solicitation_number="NSN 4320-01-481-4914",
        agency="US Coast Guard",
        due_date="2026-06-15",
        compliance_score=92,
        status="in_progress",
        created_at="2026-05-20T09:00:00Z",
        updated_at="2026-06-02T14:32:00Z",
    ),
    ProposalSummary(
        id="2",
        title="IT Support Services BPA",
        solicitation_number="W52P1J-26-R-0042",
        agency="Dept of Army",
        due_date="2026-06-28",
        compliance_score=78,
        status="review_needed",
        created_at="2026-05-25T10:00:00Z",
        updated_at="2026-06-01T11:00:00Z",
    ),
    ProposalSummary(
        id="3",
        title="Environmental Remediation SOW",
        solicitation_number="EP-W3-26-0018",
        agency="EPA",
        due_date="2026-07-03",
        compliance_score=45,
        status="incomplete",
        created_at="2026-05-28T08:00:00Z",
        updated_at="2026-05-30T16:00:00Z",
    ),
]


def mock_proposal_detail(proposal_id: str) -> Proposal:
    """Expands a summary into the full Proposal detail view."""
    summary = next(
        (p for p in MOCK_PROPOSAL_SUMMARIES if p.id == proposal_id),
        MOCK_PROPOSAL_SUMMARIES[0],
    )
    return Proposal(
        **summary.model_dump(),
        contract_type="Firm Fixed Price",
        naics_code="811310",
        naics_description="Commercial & Industrial Machinery Repair",
        pricing_model="fixed",
        target_profit_margin=12.5,
        drafting_level="technical",
        tone="formal",
        page_limit=30,
        document_id="doc-1",
        total_requirements=14,
        addressed_requirements=9,
        partial_requirements=3,
        missing_requirements=2,
    )


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------

def mock_requirements(proposal_id: str) -> list[Requirement]:
    return [
        Requirement(
            id="r1",
            proposal_id=proposal_id,
            number=1,
            section="C.3.1",
            text="The contractor shall disassemble, inspect, and overhaul the centrifugal pump assembly.",
            category="scope",
            type="mandatory",
            compliance_status="addressed",
            confidence_score=96.0,
            proposal_section_id="s1",
            proposal_section_title="Technical Approach",
            created_at="2026-05-20T09:05:00Z",
        ),
        Requirement(
            id="r2",
            proposal_id=proposal_id,
            number=2,
            section="C.3.4",
            text="All replacement parts shall conform to OEM specifications and be traceable to source.",
            category="technical",
            type="mandatory",
            compliance_status="partial",
            confidence_score=71.0,
            proposal_section_id="s1",
            proposal_section_title="Technical Approach",
            created_at="2026-05-20T09:06:00Z",
        ),
        Requirement(
            id="r3",
            proposal_id=proposal_id,
            number=3,
            section="E.2.1",
            text="The contractor shall provide a hydrostatic test report for each overhauled unit.",
            category="testing",
            type="mandatory",
            compliance_status="missing",
            confidence_score=None,
            proposal_section_id=None,
            proposal_section_title=None,
            created_at="2026-05-20T09:07:00Z",
        ),
    ]


# ---------------------------------------------------------------------------
# Proposal sections
# ---------------------------------------------------------------------------

def mock_sections(proposal_id: str) -> list[ProposalSection]:
    return [
        ProposalSection(
            id="s1",
            proposal_id=proposal_id,
            title="Technical Approach",
            content=(
                "## Technical Approach\n\n"
                "Our team will execute a full teardown and overhaul of the "
                "centrifugal pump assembly in accordance with OEM specifications..."
            ),
            status="draft",
            word_count=412,
            ai_confidence_score=88.0,
            ai_flags=[
                AIFlag(
                    id="f1",
                    message="Parts traceability language is generic — cite a specific QA clause.",
                    severity="warning",
                )
            ],
            mapped_requirement_ids=["r1", "r2"],
            reference_tags=["past-performance:USCG-2024", "capability:machining"],
            last_edited_at="2026-06-02T14:30:00Z",
            last_edited_by="Jordan Sparks",
        ),
    ]
