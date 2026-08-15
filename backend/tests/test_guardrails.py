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


def test_validate_draft_ignores_headings_by_default():
    """The plain (non-section) writer's prompt never mandates headings, so a
    heading-free draft must still pass when `require_headings` isn't opted into."""
    plain = "A properly sized draft response with no markdown structure at all."
    assert validate_draft(plain) == plain


def test_validate_draft_requires_a_heading_when_opted_in():
    """The section-drafting system prompt mandates fixed headings, telling the
    model to omit whichever ones its requirements don't support — so a compliant
    draft carries at least one, never zero. A draft that dropped the structure
    entirely reads as free-flowing prose that the length/placeholder/filler
    checks don't catch, so this is the only thing that will."""
    no_structure = (
        "We will deliver the widgets on schedule and staff the contract with "
        "cleared personnel, drawing on our prior depot maintenance work."
    )
    with pytest.raises(DraftGuardrailError, match="heading"):
        validate_draft(no_structure, require_headings=True)

    one_heading = (
        "## Technical Approach\n\n"
        "We will deliver the widgets on schedule and staff the contract with "
        "cleared personnel, drawing on our prior depot maintenance work."
    )
    assert validate_draft(one_heading, require_headings=True) == one_heading


def test_validate_draft_heading_check_is_case_tolerant():
    """A model that lowercases a heading is still structurally compliant — the
    check should not be pickier than the system prompt actually requires."""
    variant = (
        "## technical approach\n\n"
        "We will deliver the widgets on schedule under this contract."
    )
    assert validate_draft(variant, require_headings=True) == variant


def test_validate_draft_ignores_requirement_tags_by_default():
    """Traceability tags are only mandated for the section writer's prompt; a
    tag-free draft must still pass when not opted into the check."""
    untagged = (
        "A properly sized draft response with no [Req N] tags at all, long "
        "enough to clear the length floor for two requirements on its own, "
        "since that floor is scored independently of the tag check itself. "
        "It covers the delivery schedule, the staffing approach, and the "
        "quality-control process the offeror intends to follow throughout "
        "the period of performance, without citing any requirement by number."
    )
    assert validate_draft(untagged, requirement_count=2) == untagged


def test_validate_draft_requires_a_tag_per_requirement_when_opted_in():
    """A section answering 2 requirements but tagging only 1 has left the other
    untraceable — a human (or a downstream coverage check) can't confirm it was
    actually addressed without re-reading the whole section."""
    one_tagged = (
        "We will deliver the widgets on schedule, drawing on our depot overhaul "
        "experience and existing production capacity to meet the delivery date "
        "without disruption to other ongoing contract obligations. [Req 1] We "
        "will also staff the contract with cleared personnel drawn from our "
        "current workforce, all of whom already hold the required clearance "
        "level and have prior experience on similar government contracts."
    )
    with pytest.raises(DraftGuardrailError, match=r"\[2\]"):
        validate_draft(one_tagged, requirement_count=2, require_requirement_tags=True)

    both_tagged = (
        "We will deliver the widgets on schedule, drawing on our depot overhaul "
        "experience and existing production capacity to meet the delivery date "
        "without disruption to other ongoing contract obligations. [Req 1] We "
        "will also staff the contract with cleared personnel drawn from our "
        "current workforce, all of whom already hold the required clearance "
        "level and have prior experience on similar government contracts. [Req 2]"
    )
    assert (
        validate_draft(both_tagged, requirement_count=2, require_requirement_tags=True)
        == both_tagged
    )


def test_validate_draft_skips_tag_check_with_zero_requirements():
    """A brief-fallback section (the planner mapped no requirements to it) has
    nothing to tag — the check must not demand [Req 1] out of nowhere."""
    text = "A properly sized draft response with no requirements to trace at all."
    assert (
        validate_draft(text, requirement_count=0, require_requirement_tags=True)
        == text
    )


def test_validate_draft_ignores_unverifiable_facts_without_source_context():
    """The fact-check is opt-in — a caller that doesn't supply source_context
    (e.g. the plain single-requirement writer) gets no such check at all."""
    text = "Delivered under contract W91QUZ-19-C-0042 for $4,200,000 total value."
    assert validate_draft(text) == text


def test_validate_draft_rejects_a_contract_number_not_in_the_source():
    """The single highest-consequence hallucination: a fabricated award number.
    Catching it doesn't need an LLM — it just needs to not appear anywhere in
    what the writer was actually given."""
    text = "Delivered under contract W91QUZ-19-C-0042 as our flagship reference."
    with pytest.raises(DraftGuardrailError, match="W91QUZ-19-C-0042"):
        validate_draft(text, source_context="Some unrelated company profile facts.")

    assert (
        validate_draft(text, source_context="Past performance: W91QUZ-19-C-0042 — US Army.")
        == text
    )


def test_validate_draft_rejects_a_dollar_figure_not_in_the_source():
    text = "The prior contract was valued at $4,200,000 over its period of performance."
    with pytest.raises(DraftGuardrailError, match=r"4,200,000"):
        validate_draft(text, source_context="No dollar figures mentioned here.")

    assert (
        validate_draft(text, source_context="Contract value: $4,200,000, US Army.")
        == text
    )
