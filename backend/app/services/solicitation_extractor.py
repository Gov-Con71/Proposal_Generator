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
from typing import Optional, TypeVar

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
    # "light" tier: same shape of task as compliance_extractor's — literal,
    # cited, schema-constrained extraction, explicitly told not to infer or
    # extrapolate (see _SYSTEM_PROMPT) — and it runs concurrently against the
    # same document (ingestion.py's asyncio.gather), so there is no reason this
    # one call should cost more than that one. Falls back to the main model
    # when LLM_MODEL_LIGHT is unset, same no-op-by-default behaviour as there.
    return get_llm(tier="light").generate_structured(
        f"DOCUMENT TEXT:\n{document}",
        SolicitationSummary,
        system=_SYSTEM_PROMPT,
    )


# ---------------------------------------------------------------------------
# Map-reduce merge
#
# Unlike the compliance matrix (a flat list — merging chunk results is just
# concatenation), a SolicitationSummary is a single nested record: each chunk
# extraction reports its own (mostly-null) view of the *same* document-level
# fields, since e.g. the proposal due date might only appear in whichever
# chunk happens to contain the cover letter. Merging means picking, per field,
# the first chunk that actually found something — not overwriting a found
# value with a later chunk's null.
# ---------------------------------------------------------------------------

_T = TypeVar("_T", bound=BaseModel)


def _first_present(values: list[Citation]) -> Citation:
    """First citation with a non-null value; falls back to the first item (or
    an all-null Citation) so a field genuinely absent from every chunk still
    round-trips as null rather than raising on an empty list."""
    for c in values:
        if c.value is not None:
            return c
    return values[0] if values else Citation(value=None, source_quote=None)


def _dedupe(items: list[_T], key) -> list[_T]:
    """Drops items that share `key(item)` with one already kept — the same
    deliverable/instruction/etc. can legitimately be re-extracted from more
    than one chunk when the document restates it (e.g. a due date repeated in
    both a cover letter and Section L)."""
    seen: set = set()
    out: list[_T] = []
    for item in items:
        k = key(item)
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


def merge_solicitation_summaries(summaries: list[SolicitationSummary]) -> SolicitationSummary:
    """Merges one `SolicitationSummary` per document chunk into one summary.

    Single-value fields (administrative/deadlines/technical_core citations,
    the submission method) take the first chunk that reported a non-null
    value. List fields are concatenated across chunks and deduped on their
    natural identity (volume+limit, factor name, etc.) since chunk boundaries
    don't overlap by construction (`semantic_chunks`) but the same fact can
    still legitimately appear in more than one section of the source document.
    """
    if len(summaries) == 1:
        return summaries[0]

    return SolicitationSummary(
        administrative=Administrative(
            solicitation_number=_first_present([s.administrative.solicitation_number for s in summaries]),
            agency_or_organization=_first_present([s.administrative.agency_or_organization for s in summaries]),
            title_of_opportunity=_first_present([s.administrative.title_of_opportunity for s in summaries]),
            naics_code=_first_present([s.administrative.naics_code for s in summaries]),
            set_aside_type=_first_present([s.administrative.set_aside_type for s in summaries]),
        ),
        deadlines=Deadlines(
            questions_due_date=_first_present([s.deadlines.questions_due_date for s in summaries]),
            proposal_due_date=_first_present([s.deadlines.proposal_due_date for s in summaries]),
            period_of_performance=_first_present([s.deadlines.period_of_performance for s in summaries]),
        ),
        submission_requirements=SubmissionRequirements(
            submission_method=next(
                (
                    m
                    for m in (s.submission_requirements.submission_method for s in summaries)
                    if m.value is not None
                ),
                summaries[0].submission_requirements.submission_method,
            ),
            page_limits=_dedupe(
                [pl for s in summaries for pl in s.submission_requirements.page_limits],
                key=lambda pl: (pl.volume, pl.limit),
            ),
            required_volumes_or_sections=_dedupe(
                [v for s in summaries for v in s.submission_requirements.required_volumes_or_sections],
                key=lambda v: v.name,
            ),
        ),
        technical_core=TechnicalCore(
            primary_objective=_first_present([s.technical_core.primary_objective for s in summaries]),
            key_deliverables=_dedupe(
                [d for s in summaries for d in s.technical_core.key_deliverables],
                key=lambda d: d.title,
            ),
        ),
        evaluation_factors=_dedupe(
            [f for s in summaries for f in s.evaluation_factors],
            key=lambda f: f.factor,
        ),
        instructions_to_offerors=_dedupe(
            [i for s in summaries for i in s.instructions_to_offerors],
            key=lambda i: i.instruction,
        ),
    )


async def run_solicitation_extraction(markdown_text: str) -> SolicitationSummary:
    """Extracts the document-level solicitation summary from Markdown.

    A document within `settings.max_extraction_chars` takes one LLM call, same
    as before this existed. Beyond that budget, `guard_extraction_input` would
    otherwise truncate the document and silently drop tail facts (a deadline or
    Section L instruction that only appears late in a large RFP package) — same
    failure mode already fixed for the compliance matrix. This splits the
    document into heading-aware chunks (`semantic_chunks`), extracts each
    independently and concurrently, and merges the results
    (`merge_solicitation_summaries`).

    Returns a validated `SolicitationSummary`. Provider calls are synchronous;
    each is bridged to the event loop via `asyncio.to_thread`.
    """
    from app.core.config import settings
    from app.services.extraction_input import chunk_sizes
    from app.services.semantic_chunker import semantic_chunks

    if len(markdown_text) <= settings.max_extraction_chars:
        logger.info(
            "run_solicitation_extraction: sending %d chars of markdown to the LLM",
            len(markdown_text),
        )
        summary = await asyncio.to_thread(_call_extractor, markdown_text)
    else:
        target, ceiling = chunk_sizes(settings.max_extraction_chars)
        chunks = semantic_chunks(markdown_text, target_chars=target, max_chars=ceiling)
        logger.info(
            "run_solicitation_extraction: document is %d chars, over the %d "
            "extraction budget — split into %d chunk(s) for map-reduce extraction.",
            len(markdown_text),
            settings.max_extraction_chars,
            len(chunks),
        )
        summaries = await asyncio.gather(
            *(asyncio.to_thread(_call_extractor, chunk) for chunk in chunks)
        )
        summary = merge_solicitation_summaries(list(summaries))

    if summary is None:
        raise RuntimeError("Solicitation extraction returned no summary.")
    logger.info("run_solicitation_extraction: extracted solicitation summary")
    return summary
