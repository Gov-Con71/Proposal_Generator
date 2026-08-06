"""Solicitation summary extractor — document-level metadata (Sprint 8).

A complementary extraction stage that sits alongside the compliance-matrix
extractor (`compliance_extractor.py`). Where that shreds the RFP into a flat list
of per-requirement rows, this pulls the *document-level* administrative, deadline,
submission, technical-core, and Section L/M facts a proposal manager needs at a
glance — every value carrying an exact `source_quote` citation, and `null` where
the document is silent.

The result is a single `SolicitationSummary` object persisted as JSONB on
`rfp_documents.solicitation_summary`. It is supplementary: ingestion treats a
failure here as non-fatal so the core requirements pipeline is never blocked.

LLM calls go through the provider-agnostic `app.services.llm` port (Gemini today).
`_call_extractor` is isolated as a seam so tests can stub it without a live model.
"""

import asyncio
import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.services.llm import get_llm

logger = logging.getLogger(__name__)

# Structured output enforces the JSON shape, so the prompt only needs to convey
# the extraction *policy* (literal, cited, null-when-absent) — not the schema.
_SYSTEM_PROMPT = (
    "You are an expert procurement analyst and data extraction engine. Extract key "
    "administrative, technical, and compliance information from the solicitation "
    "document provided.\n"
    "STRICT LITERAL EXTRACTION: Extract information directly from the text. Do not "
    "infer, extrapolate, or assume. If a field is not explicitly present in the "
    "text, return null for that field's value (and null for its source_quote).\n"
    "CITATION REQUIREMENT: For every value you extract, populate source_quote with "
    "an exact quote or section reference proving where you found it. Whenever a "
    "value is null, its source_quote must be null too.\n"
    "For the list fields (page_limits, required_volumes_or_sections, "
    "key_deliverables, evaluation_factors, instructions_to_offerors), return an "
    "empty list if the document contains none.\n"
    "SECTIONS L AND M: pay particular attention to 'Instructions to Offerors' "
    "(Section L) and 'Evaluation Factors for Award' (Section M), which may appear "
    "under those names or as an equivalent instructions/evaluation clause. Capture "
    "every evaluation factor with its stated relative importance, and every "
    "preparation/submission instruction — a proposal that misses these is "
    "non-responsive regardless of technical merit."
)


# ---------------------------------------------------------------------------
# Structured-output schema (mirrors rfp_documents.solicitation_summary JSONB)
#
# Every field is required-but-nullable (Optional without a default): Gemini
# rejects a `default` in a response schema, and required nullable fields let the
# model emit `null` for anything the document does not state. See the drafting
# agent's ComplianceReview for the same constraint.
# ---------------------------------------------------------------------------

class Citation(BaseModel):
    value: Optional[str] = Field(description="The extracted value, or null if absent.")
    source_quote: Optional[str] = Field(
        description="Exact quote/section reference for the value, or null."
    )


class Administrative(BaseModel):
    solicitation_number: Citation
    agency_or_organization: Citation
    title_of_opportunity: Citation
    naics_code: Citation
    set_aside_type: Citation


class Deadlines(BaseModel):
    questions_due_date: Citation
    proposal_due_date: Citation
    period_of_performance: Citation


class SubmissionMethod(BaseModel):
    value: Optional[str] = Field(description="How proposals are submitted, or null.")
    description: Optional[str] = Field(
        description="Extra detail on the submission method, or null."
    )
    source_quote: Optional[str] = Field(description="Exact quote/reference, or null.")


class PageLimit(BaseModel):
    volume: str = Field(description="The volume/section the limit applies to.")
    limit: str = Field(description="The page limit as stated (e.g. '30 pages').")
    source_quote: str = Field(description="Exact quote/reference for the limit.")


class VolumeSection(BaseModel):
    name: str = Field(description="Name of the required volume or section.")
    description: str = Field(description="What the volume/section must contain.")
    source_quote: str = Field(description="Exact quote/reference.")


class SubmissionRequirements(BaseModel):
    submission_method: SubmissionMethod
    page_limits: list[PageLimit] = Field(
        description="Page limits per volume; empty list if none stated."
    )
    required_volumes_or_sections: list[VolumeSection] = Field(
        description="Required proposal volumes/sections; empty list if none stated."
    )


class Deliverable(BaseModel):
    title: str = Field(description="Short title of the deliverable.")
    description: str = Field(description="What the deliverable is.")
    source_quote: str = Field(description="Exact quote/reference.")


class TechnicalCore(BaseModel):
    primary_objective: Citation
    key_deliverables: list[Deliverable] = Field(
        description="Key deliverables; empty list if none stated."
    )


class EvaluationFactor(BaseModel):
    """One Section M factor the government will score the proposal against."""

    factor: str = Field(description="Name of the evaluation factor or subfactor.")
    description: str = Field(description="What the government will assess under it.")
    importance: str = Field(
        description=(
            "Relative importance as stated (e.g. 'significantly more important than "
            "price', 'equally weighted'); '' if the document does not say."
        )
    )
    source_quote: str = Field(description="Exact quote/reference.")


class Instruction(BaseModel):
    """One Section L instruction governing how the proposal must be prepared."""

    instruction: str = Field(description="The preparation/submission instruction.")
    applies_to: str = Field(
        description="Volume/section it governs, or 'All' when proposal-wide."
    )
    source_quote: str = Field(description="Exact quote/reference.")


class SolicitationSummary(BaseModel):
    administrative: Administrative
    deadlines: Deadlines
    submission_requirements: SubmissionRequirements
    technical_core: TechnicalCore
    # Sections M and L. Non-nullable str fields with no defaults, matching
    # PageLimit/Deliverable — a `default` in the response schema breaks Gemini,
    # and `sanitize_solicitation_summary` drops whole items whose quote is
    # fabricated (it keys off source_quote-without-value, which these match).
    evaluation_factors: list[EvaluationFactor] = Field(
        description="Section M evaluation factors; empty list if none stated."
    )
    instructions_to_offerors: list[Instruction] = Field(
        description="Section L preparation/submission instructions; empty if none."
    )


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _call_extractor(markdown_text: str) -> SolicitationSummary:
    """Structured solicitation-summary extraction via the LLM provider. Isolated
    as a seam so tests can stub it (mirrors the compliance extractor's approach)."""
    from app.services.extraction_input import guard_extraction_input

    document = guard_extraction_input(markdown_text, label="solicitation extraction")
    return get_llm().generate_structured(
        f"DOCUMENT TEXT:\n{document}",
        SolicitationSummary,
        system=_SYSTEM_PROMPT,
    )


async def run_solicitation_extraction(markdown_text: str) -> SolicitationSummary:
    """Extracts the document-level solicitation summary from Markdown.

    Returns a validated `SolicitationSummary`. The provider call is synchronous;
    it is bridged to the event loop by the caller (ingestion) via `asyncio`.
    """
    logger.info(
        "run_solicitation_extraction: sending %d chars of markdown to the LLM",
        len(markdown_text),
    )
    # The provider call is blocking; run it off the event loop so it genuinely
    # overlaps the compliance extraction that ingestion gathers alongside it.
    summary = await asyncio.to_thread(_call_extractor, markdown_text)
    if summary is None:
        raise RuntimeError("Solicitation extraction returned no summary.")
    logger.info("run_solicitation_extraction: extracted solicitation summary")
    return summary
