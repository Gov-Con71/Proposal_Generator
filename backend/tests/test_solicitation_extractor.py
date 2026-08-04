"""Unit tests for the solicitation summary extractor (Sprint 8).

Isolates the single external LLM touchpoint (`_call_extractor`) so the tests are
deterministic and need no Gemini key. Exercises the happy path, the null/empty
shape, and the ingestion shield that keeps a summary failure non-fatal.
"""

import asyncio

import pytest

from app.services import solicitation_extractor as se
from app.services.guardrails import sanitize_solicitation_summary
from app.services.solicitation_extractor import (
    Administrative,
    Citation,
    Deadlines,
    Deliverable,
    EvaluationFactor,
    Instruction,
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
        evaluation_factors=[
            EvaluationFactor(
                factor="Technical Merit",
                description="Soundness of the technical approach",
                importance="more important than price",
                source_quote="M.2 Technical Merit is more important than price",
            )
        ],
        instructions_to_offerors=[
            Instruction(
                instruction="Submit Volume I in Times New Roman 12pt",
                applies_to="Volume I",
                source_quote="L.4 Format: Times New Roman 12pt",
            )
        ],
    )


def test_run_solicitation_extraction_returns_validated_summary(monkeypatch):
    monkeypatch.setattr(se, "_call_extractor", lambda md: _full_summary())

    summary = asyncio.run(se.run_solicitation_extraction("some markdown"))

    dumped = summary.model_dump()
    # Matches the agreed output schema exactly, top to bottom.
    assert set(dumped) == {
        "administrative",
        "deadlines",
        "submission_requirements",
        "technical_core",
        "evaluation_factors",
        "instructions_to_offerors",
    }
    assert dumped["administrative"]["solicitation_number"] == {
        "value": "W912-25-R-0001",
        "source_quote": "Solicitation No. W912-25-R-0001",
    }
    assert dumped["submission_requirements"]["page_limits"][0]["limit"] == "30 pages"
    assert dumped["technical_core"]["key_deliverables"][0]["title"] == "Monthly report"
    # Sections M and L — what the proposal is scored on, and how it must be built.
    assert dumped["evaluation_factors"][0]["factor"] == "Technical Merit"
    assert dumped["evaluation_factors"][0]["importance"] == "more important than price"
    assert dumped["instructions_to_offerors"][0]["applies_to"] == "Volume I"


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
        evaluation_factors=[],
        instructions_to_offerors=[],
    )
    monkeypatch.setattr(se, "_call_extractor", lambda md: empty)

    dumped = asyncio.run(se.run_solicitation_extraction("x")).model_dump()
    assert dumped["administrative"]["naics_code"] == {"value": None, "source_quote": None}
    assert dumped["submission_requirements"]["page_limits"] == []
    assert dumped["technical_core"]["key_deliverables"] == []
    assert dumped["evaluation_factors"] == []
    assert dumped["instructions_to_offerors"] == []


def test_none_result_raises(monkeypatch):
    monkeypatch.setattr(se, "_call_extractor", lambda md: None)
    with pytest.raises(RuntimeError):
        asyncio.run(se.run_solicitation_extraction("x"))


def test_fabricated_section_l_and_m_citations_are_dropped():
    """The Section L/M lists inherit the existing citation check for free: their
    items are source_quote-bearing dicts with no `value` key, the shape
    `sanitize_solicitation_summary` drops whole when the quote isn't in the source.

    This matters more here than elsewhere — an invented evaluation factor would
    silently steer every section of the proposal at the wrong target.
    """
    summary = _full_summary().model_dump()
    source = (
        "L.4 Format: Times New Roman 12pt. "
        "M.2 Technical Merit is more important than price"
    )
    # Add a factor whose citation appears nowhere in the source document.
    summary["evaluation_factors"].append(
        {
            "factor": "Small Business Participation",
            "description": "Invented factor",
            "importance": "critical",
            "source_quote": (
                "M.9 Small Business Participation shall be weighted above all "
                "other factors in this procurement"
            ),
        }
    )

    clean, removed = sanitize_solicitation_summary(summary, source)

    assert removed == 1
    factors = [f["factor"] for f in clean["evaluation_factors"]]
    assert factors == ["Technical Merit"]
    # The grounded Section L instruction is untouched.
    assert len(clean["instructions_to_offerors"]) == 1
