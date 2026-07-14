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
