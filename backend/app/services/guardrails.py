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
                search_keywords=r.search_keywords,
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

# The section system prompt mandates these as the only allowed structure,
# telling the model to omit whichever ones its requirements don't support — so
# a compliant draft carries at least one, never zero. A draft with none of them
# ignored the structural instruction wholesale and came back as free-flowing
# prose, which the length/placeholder/filler checks below don't catch at all.
_REQUIRED_HEADING_PATTERN = re.compile(
    r"^##\s*(Understanding of the Requirement|Technical Approach|"
    r"Management Plan|Differentiators)\b",
    re.IGNORECASE | re.MULTILINE,
)

# The section system prompt requires every requirement to get an inline
# `[Req N]` tag somewhere in the section (1-indexed, matching the numbered list
# the writer was given). This is what turns "the critic judged coverage
# holistically" into a deterministic, per-requirement, unconditional check that
# doesn't depend on an LLM call succeeding.
_REQUIREMENT_TAG_PATTERN = re.compile(r"\[Req (\d+)\]")

# Heuristic shape for the contract numbers this codebase's own past-performance
# data uses (see COMPANY PROFILE formatting in draft_writer.py): a DoD/GSA-style
# award number like "W91QUZ-19-C-0042" or "FA8750-20-C-0001" — letters/digits,
# 2-digit year, single-letter contract type, numeric serial. Not exhaustive of
# every federal contract-number format, but catches the common shape well
# enough to flag the highest-consequence hallucination (a fabricated award
# number) without an LLM call.
_CONTRACT_NUMBER_PATTERN = re.compile(r"\b[A-Z0-9]{5,}-\d{2}-[A-Z]-\d{4,}\b")
_DOLLAR_FIGURE_PATTERN = re.compile(r"\$[\d,]+(?:\.\d+)?")


def _missing_requirement_tags(text: str, requirement_count: int) -> list[int]:
    """Requirement numbers (1..requirement_count) with no `[Req N]` tag in `text`."""
    tagged = {int(n) for n in _REQUIREMENT_TAG_PATTERN.findall(text)}
    return [i for i in range(1, requirement_count + 1) if i not in tagged]


def _unverifiable_facts(text: str, source_context: str) -> list[str]:
    """Contract numbers / dollar figures asserted in `text` that appear nowhere
    in `source_context` (the company profile + retrieved evidence the writer
    was actually given) — the cheapest, highest-consequence hallucination to
    catch deterministically: a fabricated award number or price figure."""
    unverifiable = []
    for pattern in (_CONTRACT_NUMBER_PATTERN, _DOLLAR_FIGURE_PATTERN):
        for match in pattern.findall(text):
            if match not in source_context:
                unverifiable.append(match)
    return unverifiable


def validate_draft(
    content: str,
    requirement_count: int = 0,
    require_headings: bool = False,
    require_requirement_tags: bool = False,
    source_context: str | None = None,
) -> str:
    """Returns a trimmed draft, or raises DraftGuardrailError if unusable.

    Beyond the length floor this rejects the failure shapes that otherwise
    reach reviewers as finished text: unfilled placeholders, prose padded with
    banned superlatives instead of evidence, a draft that dropped the mandated
    section structure entirely (`require_headings`), a requirement with no
    inline traceability tag (`require_requirement_tags`), and — when
    `source_context` is supplied — a cited contract number or dollar figure
    that appears nowhere in what the writer was actually given.
    `requirement_count` scales the length floor so a token response to a
    multi-requirement section is caught. The opt-in flags default off because
    only the section-drafting system prompt (`_SECTION_SYSTEM_PROMPT`) mandates
    fixed headings and requirement tags; the plain single-requirement writer
    does not.
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

    if require_headings and not _REQUIRED_HEADING_PATTERN.search(text):
        raise DraftGuardrailError(
            "Generated draft has none of the required section headings "
            "(## Understanding of the Requirement / ## Technical Approach / "
            "## Management Plan / ## Differentiators) — refusing to save."
        )

    if require_requirement_tags and requirement_count > 0:
        missing = _missing_requirement_tags(text, requirement_count)
        if missing:
            raise DraftGuardrailError(
                f"Requirement(s) {missing} have no [Req N] traceability tag "
                "— refusing to save."
            )

    if source_context is not None:
        unverifiable = _unverifiable_facts(text, source_context)
        if unverifiable:
            raise DraftGuardrailError(
                f"Generated draft cites contract number(s)/dollar figure(s) "
                f"{unverifiable} that appear nowhere in the supplied context "
                "— refusing to save as a likely hallucination."
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
