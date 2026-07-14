"""AI output guardrails (Story 4.3).

The extractor and draft writer already get Pydantic *type* validation for free
via structured output. This layer adds *semantic* validation — catching and
rejecting malformed or hallucinated content before it is persisted.
"""

import logging

from app.services.compliance_extractor import ComplianceMatrix, ExtractedRequirement

logger = logging.getLogger(__name__)

_MIN_REQUIREMENT_CHARS = 5
_MAX_REQUIREMENT_CHARS = 4000
_MIN_DRAFT_CHARS = 20


class DraftGuardrailError(Exception):
    """Raised when a generated draft fails validation and must not be saved."""


def sanitize_matrix(matrix: ComplianceMatrix) -> tuple[ComplianceMatrix, int]:
    """Cleans an extracted compliance matrix, returning (clean_matrix, rejected_count).

    Rejects blank/too-short items (a common hallucination shape), de-duplicates
    identical requirements, trims whitespace, caps runaway length, and defaults
    a missing section label. Category is already constrained by the Literal type.
    """
    seen: set[str] = set()
    clean: list[ExtractedRequirement] = []

    for r in matrix.requirements:
        text = (r.raw_text_content or "").strip()
        if len(text) < _MIN_REQUIREMENT_CHARS:
            continue
        if len(text) > _MAX_REQUIREMENT_CHARS:
            text = text[:_MAX_REQUIREMENT_CHARS].rstrip()
        dedupe_key = text.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        clean.append(
            ExtractedRequirement(
                section_number=(r.section_number or "").strip() or "N/A",
                raw_text_content=text,
                category=r.category,
            )
        )

    rejected = len(matrix.requirements) - len(clean)
    if rejected:
        logger.info("sanitize_matrix: rejected %d malformed/duplicate requirement(s)", rejected)
    return ComplianceMatrix(requirements=clean), rejected


def validate_draft(content: str) -> str:
    """Returns a trimmed draft, or raises DraftGuardrailError if unusable."""
    text = (content or "").strip()
    if len(text) < _MIN_DRAFT_CHARS:
        raise DraftGuardrailError(
            f"Generated draft is too short ({len(text)} chars) — refusing to save."
        )
    return text
