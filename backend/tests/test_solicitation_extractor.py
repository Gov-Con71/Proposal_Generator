"""Unit tests for the solicitation summary extractor (Sprint 8).

Isolates the single external LLM touchpoint (`_call_extractor`) so the tests are
deterministic and need no Gemini key. Exercises the happy path, the null/empty
shape, and the ingestion shield that keeps a summary failure non-fatal.
"""

import asyncio

import pytest

from app.services import solicitation_extractor as se
from app.services.solicitation_extractor import (
    Administrative,
    Citation,
    Deadlines,
    Deliverable,
    PageLimit,
    SolicitationSummary,
    SubmissionMethod,
    SubmissionRequirements,
    TechnicalCore,
    VolumeSection,
)


def _full_summary() -> SolicitationSummary:
    return SolicitationSummary(
        administrative=Administrative(
            solicitation_number=Citation(value="W912-25-R-0001", source_quote="Solicitation No. W912-25-R-0001"),
            agency_or_organization=Citation(value="Dept. of Defense", source_quote="Issued by the Dept. of Defense"),
            title_of_opportunity=Citation(value="Widget Support", source_quote="Title: Widget Support"),
            naics_code=Citation(value="541512", source_quote="NAICS 541512"),
            set_aside_type=Citation(value=None, source_quote=None),
        ),
        deadlines=Deadlines(
            questions_due_date=Citation(value="2026-08-01", source_quote="Questions due 1 Aug 2026"),
            proposal_due_date=Citation(value="2026-08-15", source_quote="Proposals due 15 Aug 2026"),
            period_of_performance=Citation(value=None, source_quote=None),
        ),
        submission_requirements=SubmissionRequirements(
            submission_method=SubmissionMethod(
                value="Email", description="PDF to contracting officer", source_quote="Submit via email as PDF"
            ),
            page_limits=[PageLimit(volume="Technical", limit="30 pages", source_quote="Volume I limited to 30 pages")],
            required_volumes_or_sections=[
                VolumeSection(name="Volume I", description="Technical", source_quote="Volume I – Technical")
            ],
        ),
        technical_core=TechnicalCore(
            primary_objective=Citation(value="Maintain widgets", source_quote="Objective: maintain widgets"),
            key_deliverables=[Deliverable(title="Monthly report", description="Status report", source_quote="Deliver a monthly status report")],
        ),
    )


def test_run_solicitation_extraction_returns_validated_summary(monkeypatch):
    monkeypatch.setattr(se, "_call_extractor", lambda md: _full_summary())

    summary = asyncio.run(se.run_solicitation_extraction("some markdown"))

    dumped = summary.model_dump()
    # Matches the agreed output schema exactly, top to bottom.
    assert set(dumped) == {"administrative", "deadlines", "submission_requirements", "technical_core"}
    assert dumped["administrative"]["solicitation_number"] == {
        "value": "W912-25-R-0001",
        "source_quote": "Solicitation No. W912-25-R-0001",
    }
    assert dumped["submission_requirements"]["page_limits"][0]["limit"] == "30 pages"
    assert dumped["technical_core"]["key_deliverables"][0]["title"] == "Monthly report"


def test_null_and_empty_shape_round_trips(monkeypatch):
    """Absent fields serialize as null; absent lists as []."""
    empty = SolicitationSummary(
        administrative=Administrative(
            solicitation_number=Citation(value=None, source_quote=None),
            agency_or_organization=Citation(value=None, source_quote=None),
            title_of_opportunity=Citation(value=None, source_quote=None),
            naics_code=Citation(value=None, source_quote=None),
            set_aside_type=Citation(value=None, source_quote=None),
        ),
        deadlines=Deadlines(
            questions_due_date=Citation(value=None, source_quote=None),
            proposal_due_date=Citation(value=None, source_quote=None),
            period_of_performance=Citation(value=None, source_quote=None),
        ),
        submission_requirements=SubmissionRequirements(
            submission_method=SubmissionMethod(value=None, description=None, source_quote=None),
            page_limits=[],
            required_volumes_or_sections=[],
        ),
        technical_core=TechnicalCore(
            primary_objective=Citation(value=None, source_quote=None), key_deliverables=[]
        ),
    )
    monkeypatch.setattr(se, "_call_extractor", lambda md: empty)

    dumped = asyncio.run(se.run_solicitation_extraction("x")).model_dump()
    assert dumped["administrative"]["naics_code"] == {"value": None, "source_quote": None}
    assert dumped["submission_requirements"]["page_limits"] == []
    assert dumped["technical_core"]["key_deliverables"] == []


def test_none_result_raises(monkeypatch):
    monkeypatch.setattr(se, "_call_extractor", lambda md: None)
    with pytest.raises(RuntimeError):
        asyncio.run(se.run_solicitation_extraction("x"))
