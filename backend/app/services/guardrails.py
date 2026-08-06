"""AI output guardrails (Story 4.3).

The extractor and draft writer already get Pydantic *type* validation for free
via structured output. This layer adds *semantic* validation — catching and
rejecting malformed or hallucinated content before it is persisted.
"""

import logging
import re

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


# Unfilled template markers. A draft carrying one of these is a partial
# generation, not a proposal — it must never reach a reviewer as finished prose.
_PLACEHOLDER_PATTERNS = (
    r"\[insert[^\]]*\]",
    r"\[your[^\]]*\]",
    r"\[company[^\]]*\]",
    r"\[tbd[^\]]*\]",
    r"\bTBD\b",
    r"\bXXX+\b",
    r"\blorem ipsum\b",
    r"<[a-z_ ]*placeholder[a-z_ ]*>",
)

# Content-free superlatives. The drafting system prompt bans these outright, so
# their presence means the model ignored the instruction and is padding rather
# than evidencing. A couple slipping through is tolerable; a pile of them is not.
_BANNED_PHRASES = (
    "world-class",
    "world class",
    "best-in-class",
    "best in class",
    "industry-leading",
    "industry leading",
    "cutting-edge",
    "cutting edge",
    "state-of-the-art",
    "state of the art",
    "seamless",
    "leverage synergies",
    "robust solution",
    "passion for excellence",
    "trusted partner",
    "unparalleled",
)
_MAX_BANNED_PHRASES = 3

# A section answering several requirements needs room to address each one; a
# 200-char reply to six requirements has not engaged with them.
_MIN_CHARS_PER_REQUIREMENT = 150


def validate_draft(content: str, requirement_count: int = 0) -> str:
    """Returns a trimmed draft, or raises DraftGuardrailError if unusable.

    Beyond the length floor this rejects the two failure shapes that otherwise
    reach reviewers as finished text: unfilled placeholders, and prose padded
    with banned superlatives instead of evidence. `requirement_count` scales the
    length floor so a token response to a multi-requirement section is caught.
    """
    text = (content or "").strip()
    if len(text) < _MIN_DRAFT_CHARS:
        raise DraftGuardrailError(
            f"Generated draft is too short ({len(text)} chars) — refusing to save."
        )

    min_chars = max(_MIN_DRAFT_CHARS, requirement_count * _MIN_CHARS_PER_REQUIREMENT)
    if len(text) < min_chars:
        raise DraftGuardrailError(
            f"Generated draft is too short ({len(text)} chars) for "
            f"{requirement_count} requirement(s); expected at least {min_chars}."
        )

    found = [p for p in _PLACEHOLDER_PATTERNS if re.search(p, text, re.IGNORECASE)]
    if found:
        raise DraftGuardrailError(
            f"Generated draft contains unfilled placeholder(s) matching {found} "
            "— refusing to save."
        )

    lowered = text.lower()
    banned = [p for p in _BANNED_PHRASES if p in lowered]
    if len(banned) > _MAX_BANNED_PHRASES:
        raise DraftGuardrailError(
            f"Generated draft is filler-heavy ({len(banned)} banned phrases: "
            f"{banned}) — refusing to save."
        )
    if banned:
        logger.info("validate_draft: draft contains banned phrase(s) %s", banned)
    return text


# Only substantial quotes are verified against the source; a short `source_quote`
# is often a section reference ("Section C.3.2") that need not appear verbatim, so
# judging it would produce false positives.
_MIN_QUOTE_VERIFY_CHARS = 40


def _normalize(text: str) -> str:
    """Whitespace-collapsed, lower-cased form for tolerant substring matching."""
    return " ".join(text.split()).lower()


def sanitize_solicitation_summary(summary: dict, source_text: str) -> tuple[dict, int]:
    """Drops solicitation-summary claims whose citation can't be found in the source.

    The extractor is told to quote the document for every value, but a model can
    still fabricate a quote. This verifies each substantial `source_quote` against
    the (normalized) source text and removes the ones that aren't grounded:

      * value+source_quote nodes (administrative/deadline/technical citations,
        submission_method) — value and source_quote are nulled.
      * list items (page limits, required volumes, deliverables) — the whole item
        is dropped, since its fields are non-nullable.

    Short quotes / section references are left untouched (see _MIN_QUOTE_VERIFY_CHARS).
    Returns (clean_summary, removed_count); non-destructive to grounded data.
    """
    norm_src = _normalize(source_text)

    def _ungrounded(node: dict) -> bool:
        quote = node.get("source_quote")
        if not quote:
            return False
        norm_quote = _normalize(quote)
        if len(norm_quote) < _MIN_QUOTE_VERIFY_CHARS:
            return False
        return norm_quote not in norm_src

    removed = 0

    def _clean(node):
        nonlocal removed
        if isinstance(node, dict):
            # A citation-shaped node: null it whole when its quote is fabricated.
            if "source_quote" in node and "value" in node and _ungrounded(node):
                removed += 1
                node = {**node, "value": None, "source_quote": None}
            return {k: _clean(v) for k, v in node.items()}
        if isinstance(node, list):
            kept = []
            for item in node:
                if (
                    isinstance(item, dict)
                    and "source_quote" in item
                    and "value" not in item
                    and _ungrounded(item)
                ):
                    removed += 1
                    continue
                kept.append(_clean(item))
            return kept
        return node

    return _clean(summary), removed
