"""Proposal list/detail contract (mock) — Story 1.3.

Only the proposal *list* and *detail* remain mocked (no proposals table yet).
Requirements and sections are served by the real workspace router (Story 3.4).
"""

from fastapi import APIRouter, Depends

from app.api.mock.data import MOCK_PROPOSAL_SUMMARIES, mock_proposal_detail
from app.core.deps import get_current_user_id
from app.models.contract import Proposal, ProposalSummary

# Require a valid session for every proposal route (Story 4.2 request isolation).
router = APIRouter(
    prefix="/proposals",
    tags=["Proposals (mock)"],
    dependencies=[Depends(get_current_user_id)],
)


@router.get("", response_model=list[ProposalSummary], summary="List proposals")
def list_proposals() -> list[ProposalSummary]:
    return MOCK_PROPOSAL_SUMMARIES


@router.get("/{proposal_id}", response_model=Proposal, summary="Get proposal detail")
def get_proposal(proposal_id: str) -> Proposal:
    return mock_proposal_detail(proposal_id)
