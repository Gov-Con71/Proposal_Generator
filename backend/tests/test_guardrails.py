"""Story 4.3 — AI output guardrail unit tests (no DB / no LLM)."""

import pytest

from app.services.compliance_extractor import ComplianceMatrix, ExtractedRequirement
from app.services.guardrails import DraftGuardrailError, sanitize_matrix, validate_draft


def _req(text, section="C.1", category="Technical"):
    return ExtractedRequirement(section_number=section, raw_text_content=text, category=category)


def test_sanitize_drops_blank_and_duplicates():
    matrix = ComplianceMatrix(
        requirements=[
            _req("The contractor SHALL deliver widgets."),
            _req("   "),                                   # blank -> reject
            _req("x"),                                     # too short -> reject
            _req("The contractor SHALL deliver widgets."),  # duplicate -> reject
        ]
    )
    clean, rejected = sanitize_matrix(matrix)
    assert len(clean.requirements) == 1
    assert rejected == 3


def test_sanitize_defaults_missing_section_and_trims():
    matrix = ComplianceMatrix(requirements=[_req("  MFA is REQUIRED.  ", section="  ")])
    clean, _ = sanitize_matrix(matrix)
    assert clean.requirements[0].section_number == "N/A"
    assert clean.requirements[0].raw_text_content == "MFA is REQUIRED."


def test_sanitize_caps_runaway_length():
    clean, _ = sanitize_matrix(ComplianceMatrix(requirements=[_req("A" * 9000)]))
    assert len(clean.requirements[0].raw_text_content) <= 4000


def test_validate_draft_accepts_and_rejects():
    assert validate_draft("  A properly sized draft response.  ") == "A properly sized draft response."
    with pytest.raises(DraftGuardrailError):
        validate_draft("too short")
    with pytest.raises(DraftGuardrailError):
        validate_draft("   ")


def test_validate_draft_rejects_unfilled_placeholders():
    """A draft carrying a template marker is a partial generation, not prose —
    it must never reach a reviewer looking finished."""
    for draft in (
        "Our firm, [INSERT COMPANY NAME], will perform the depot overhaul work.",
        "The contractor will deliver the widgets by TBD under this contract.",
        "Delivery occurs at [Your Facility] following government acceptance.",
        "Pricing for the base period is $XXXX under the resulting contract.",
    ):
        with pytest.raises(DraftGuardrailError, match="placeholder"):
            validate_draft(draft)


def test_validate_draft_rejects_filler_heavy_prose():
    """Banned superlatives are prohibited by the drafting prompt; a pile of them
    means the model padded instead of evidencing."""
    filler = (
        "Our world-class team delivers best-in-class, industry-leading, "
        "cutting-edge solutions with seamless integration and unparalleled value."
    )
    with pytest.raises(DraftGuardrailError, match="filler-heavy"):
        validate_draft(filler)

    # A single lapse is tolerated — rejecting the whole draft over one word would
    # discard otherwise usable prose.
    tolerable = (
        "Our team maintained a 99.2% on-time delivery rate across 412 depot "
        "overhauls under W91QUZ-19-C-0042, with seamless handover at closeout."
    )
    assert validate_draft(tolerable) == tolerable


def test_validate_draft_length_floor_scales_with_requirement_count():
    """A token reply to a multi-requirement section has not engaged with it."""
    short = "We will comply with all of the requirements stated in this section."
    assert validate_draft(short) == short              # no requirement count given
    assert validate_draft(short, requirement_count=0) == short

    with pytest.raises(DraftGuardrailError, match="requirement"):
        validate_draft(short, requirement_count=6)
