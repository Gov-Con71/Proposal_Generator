"""Proposal drafting agent — the AI writer (Sprint 3).

Turns an RFP's extracted compliance matrix into a full set of drafted
`proposal_sections`:

    load_context → plan_outline → fan out over sections (bounded concurrency):
        (draft_section → check_compliance → [revise ↺ | save_section]) → END

Loading and planning run once up front; each planned section is then drafted by
its own bounded LangGraph subgraph, and up to `settings.draft_max_concurrency` sections draft
in parallel (they are independent). Each section is grounded in the tenant's
past-performance context via the RAG retriever (`generate_section_draft`),
reviewed by a compliance critic that can send it back for up to `_MAX_ATTEMPTS`
revisions, and guardrail-validated before it is persisted.

Compliance frame. A section is only as good as the facts and rules it is written
against, so every draft and review call carries three things beyond the
requirement text: the tenant's **company profile** (CAGE/UEI, set-aside status,
clearances, prior contracts — the only facts a claim may cite), the
**solicitation context** (agency, objective, deadlines, page limits, Section L
instructions), and the section's **Section M evaluation criteria**. The outline
itself mirrors the RFP's own required volumes when it states any, since a
proposal organised differently from Section L is non-responsive.

Design mirrors `compliance_extractor.py`: langgraph is imported lazily so this
module stays import-safe and out of the API import chain; LLM calls go through
the provider-agnostic `app.services.llm` port (telemetry lives in the adapter).
"""

import asyncio
import logging
from typing import Optional, TypedDict
from uuid import UUID

from pydantic import BaseModel, Field

from app.core import cache
from app.core.config import settings
from app.services import document_service as docs
from app.services import profile_service
from app.services import proposals_service
from app.services.compliance_extractor import (
    ANSWERABLE_CATEGORIES,
    EVALUATION_CATEGORY,
    INSTRUCTION_CATEGORY,
)
from app.services.draft_writer import (
    _format_company_profile,
    generate_section_draft,
    grounding_confidence,
    reference_tags,
)
from app.services.guardrails import DraftGuardrailError
from app.services.llm import get_llm
from app.services.retrieval import tenant_history_count

logger = logging.getLogger(__name__)

_OUTLINE_SYSTEM_PROMPT = (
    "You are a lead proposal manager building a proposal's section outline.\n"
    "\n"
    "STRUCTURE — if the solicitation states required volumes or sections (Section "
    "L), those ARE the outline: create one section per required volume/section, "
    "using the government's own names, in the government's own order. A proposal "
    "whose structure does not mirror Section L is non-responsive, so never "
    "substitute your own organisation for a stated one.\n"
    "Only when the solicitation states no required structure should you group the "
    "requirements yourself, by distinct subject-matter theme (e.g. Packaging & "
    "Preservation, Marking & Labeling, Quality Assurance, Security, Past "
    "Performance) — typically 4-8 sections for a substantial RFP. In that case do "
    "NOT collapse unrelated requirements into one giant catch-all 'Technical "
    "Approach'; split by subject so each section is narrow enough to write and "
    "review on its own.\n"
    "\n"
    "ASSIGNMENT — assign every requirement to exactly one section by its reference "
    "number. Do not invent requirements; only use the reference numbers provided.\n"
    "\n"
    "EVALUATION — map each section to the evaluation criteria (Section M) it will "
    "be scored under, by criterion reference number. A section may map to several, "
    "or to none.\n"
    "\n"
    "WIN THEMES — for each section give 1-2 specific discriminators: concrete "
    "reasons this offeror should win on that section, drawn from the company "
    "profile provided. Discriminators must be verifiable claims (a clearance "
    "level, a certification, a named prior contract), never generic superlatives.\n"
    "\n"
    "LENGTH — set target_words from any stated page limit that applies to the "
    "section (roughly 500 words per page, divided across the sections in that "
    "volume). Use 0 when no page limit applies."
)
_CRITIC_SYSTEM_PROMPT = (
    "You are a government-contracts compliance reviewer running a red-team pass "
    "on a proposal section before submission. Judge the draft on six independent "
    "dimensions:\n"
    "\n"
    "1. addressed — does the draft fully and verifiably answer EVERY numbered "
    "requirement? Anything missing or vague makes this false.\n"
    "2. evaluation_alignment — does the draft explicitly speak to the evaluation "
    "criteria it will be scored under? A draft that is compliant but never engages "
    "the stated criteria makes this false. When no criteria are supplied, set it "
    "true.\n"
    "3. unsupported_claims — list any capability, metric, certification, clearance, "
    "or contract reference asserted in the draft that is NOT backed by the company "
    "profile or past-performance context supplied. These are the claims that get an "
    "offeror eliminated, so be thorough.\n"
    "4. filler_found — list any content-free corporate phrasing: unsubstantiated "
    "superlatives, boilerplate, or sentences that restate the requirement instead "
    "of answering it.\n"
    "5. cited_sources — of the RETRIEVED EVIDENCE CHUNKS provided (each labeled "
    "'[source_name — relevance N]'), list the exact source_name of every one whose "
    "content is actually reflected in a claim the draft makes. A chunk that was "
    "supplied but never drawn on does not belong in this list — only report a "
    "source when the draft is actually leaning on it, not merely from the fact "
    "that it was retrieved. Empty list if none were used or none were supplied.\n"
    "6. benefit_mapped — does every substantive capability claim chain a feature/"
    "method to a stated operational benefit for the government (not left implicit), "
    "and is that benefit tied to a named evaluation criterion when criteria are "
    "supplied? A claim that names a feature and cites proof but never says why it "
    "matters to the government is a feature dump, not a scored argument — this is "
    "false if even one substantive claim in the draft has this shape.\n"
    "\n"
    "Then write feedback: specific, actionable notes naming exactly what to fix, or "
    "an empty string when the draft passes on all six. Be strict but fair — do not "
    "demand facts the writer was given no source for; the correct fix for those is "
    "a stated assumption, not an invention."
)

# LangGraph counts every node visit against a recursion limit (default 25). One
# section's draft→check→save subgraph plus its revisions stays well under that,
# but we keep a comfortable ceiling in case _MAX_ATTEMPTS is raised.
_RECURSION_LIMIT = 50

# Total draft attempts per section (1 initial + up to 2 critic-driven revisions).
_MAX_ATTEMPTS = 3

# How many sections draft concurrently is configurable (settings.draft_max_concurrency):
# sections are independent so we fan out, but each fires several LLM calls, so the
# cap bounds concurrent provider requests to stay clear of per-minute rate limits.


# ---------------------------------------------------------------------------
# Structured-output schema for the planner
# ---------------------------------------------------------------------------

class PlannedSection(BaseModel):
    section_title: str
    requirement_refs: list[int] = Field(
        default_factory=list,
        description="Reference numbers of the requirements this section covers.",
    )
    evaluation_criteria_refs: list[int] = Field(
        default_factory=list,
        description="Reference numbers of the evaluation criteria this section is scored under.",
    )
    win_themes: list[str] = Field(
        default_factory=list,
        description="1-2 verifiable discriminators for this section.",
    )
    brief: str = Field(description="1–2 sentences on what this section must cover.")
    # Required rather than defaulted (Gemini rejects defaults); 0 means "no stated
    # page limit", which the caller maps back to None.
    target_words: int = Field(
        description="Approximate word budget from any stated page limit; 0 if none."
    )


class ProposalOutline(BaseModel):
    sections: list[PlannedSection]


class ComplianceReview(BaseModel):
    """The red-team verdict: compliance, scoring alignment, evidence, and filler.

    Note the field style throughout: Gemini rejects any `default` in a
    structured-output response schema (a `Field(default=...)` here silently broke
    the critic on every run), so scalars are required and lists use
    `default_factory`. The prompt tells the model what to emit when a dimension
    passes — "" for feedback, empty lists for the two findings fields.
    """

    addressed: bool = Field(
        description="True only if the draft satisfies every requirement."
    )
    evaluation_alignment: bool = Field(
        description="True only if the draft speaks to the evaluation criteria it is scored under."
    )
    benefit_mapped: bool = Field(
        description=(
            "True only if every substantive claim chains feature -> stated "
            "government benefit -> proof, with the benefit tied to a named "
            "evaluation criterion when criteria are supplied."
        )
    )
    unsupported_claims: list[str] = Field(
        default_factory=list,
        description="Claims asserted without backing in the supplied profile or context.",
    )
    filler_found: list[str] = Field(
        default_factory=list,
        description="Content-free corporate phrasing found in the draft.",
    )
    cited_sources: list[str] = Field(
        default_factory=list,
        description="source_name of every retrieved evidence chunk actually reflected in a draft claim.",
    )
    feedback: str = Field(
        description="Specific gaps to fix; empty string when the draft passes."
    )

    def passes(self) -> bool:
        """True when the draft clears every dimension and needs no revision."""
        return (
            self.addressed
            and self.evaluation_alignment
            and self.benefit_mapped
            and not self.unsupported_claims
            and not self.filler_found
        )


# ---------------------------------------------------------------------------
# Per-section graph state
# ---------------------------------------------------------------------------

class DraftingState(TypedDict):
    # The proposal being drafted, not the RFP behind it: sections are saved
    # against it, and one RFP may back several proposals.
    proposal_id: str
    uploaded_by: str
    section: dict                    # one resolved section (title/brief/requirements/criteria/content)
    sol_context: Optional[str]       # document-level framing from the solicitation summary
    company_context: Optional[str]   # the offeror's verifiable facts from company_profiles
    retrieval_filters: Optional[dict]  # knowledge-base pre-filter (industry/document_type/
                                        # outcome — see retrieval.search_similar), None means
                                        # unfiltered, the default for every caller today
    attempts: int                    # draft attempts spent on this section
    feedback: Optional[str]          # latest critic feedback (used for review_notes)
    feedback_history: list[str]      # every round's critic feedback, oldest first —
                                      # threaded into the next attempt so a revision
                                      # doesn't blindly re-break what an earlier round fixed
    cited_sources: Optional[list[str]]  # source_names the last critic review found
                                         # actually reflected in the draft; None until
                                         # a critic review has run against the current content
    prior_findings: Optional[frozenset]  # unsupported_claims|filler_found from the
                                          # previous round, to detect a non-converging loop
    stalled: bool                    # True once a revision repeated the prior round's
                                      # exact findings — stop spending budget on it
    section_id: Optional[str]        # id of the persisted section, set by save_section


# ---------------------------------------------------------------------------
# Loading + planning (run once, up front)
# ---------------------------------------------------------------------------

def _load_context(rfp_id: UUID) -> tuple[str, list[dict], Optional[dict], object]:
    """Loads the document owner, its extracted requirements, the extracted
    solicitation summary framing the opportunity, and the tenant's company profile.

    The profile is read once per run (not per section): it is the offeror's
    factual base — CAGE/UEI, set-aside status, clearances, prior contracts — and
    without it the writer has no concrete evidence to cite.
    """
    document = docs.get_document(rfp_id)
    requirements = docs.get_requirements(rfp_id)
    if not requirements:
        raise RuntimeError(
            f"No extracted requirements for rfp {rfp_id}; run ingestion first."
        )
    summary = docs.get_solicitation_summary(rfp_id)
    uploaded_by = str(document["uploaded_by"])
    profile = profile_service.get_profile(UUID(uploaded_by))
    logger.info("drafting: loaded %d requirement(s) for rfp %s", len(requirements), rfp_id)
    return uploaded_by, requirements, summary, profile


def _format_solicitation_context(summary: Optional[dict]) -> Optional[str]:
    """Condenses the solicitation summary into a framing block for the drafting
    and review prompts. Returns None when nothing usable was extracted.

    Carries the document-level facts a section must be responsive to: who is
    buying and what for, when it is due, how it must be submitted, how long it
    may be, and what it must deliver. Kept to one terse line per fact — this
    block is repeated on every section's draft and review calls.
    """
    if not summary:
        return None

    def _value(section: str, field: str) -> Optional[str]:
        node = (summary.get(section) or {}).get(field)
        return node.get("value") if isinstance(node, dict) else None

    fields = [
        ("Opportunity", _value("administrative", "title_of_opportunity")),
        ("Agency", _value("administrative", "agency_or_organization")),
        ("Solicitation #", _value("administrative", "solicitation_number")),
        ("NAICS", _value("administrative", "naics_code")),
        ("Set-aside", _value("administrative", "set_aside_type")),
        ("Primary objective", _value("technical_core", "primary_objective")),
        ("Proposal due", _value("deadlines", "proposal_due_date")),
        ("Period of performance", _value("deadlines", "period_of_performance")),
    ]
    lines = [f"- {label}: {value}" for label, value in fields if value]

    submission = (summary.get("submission_requirements") or {})
    method = submission.get("submission_method") or {}
    if isinstance(method, dict) and method.get("value"):
        detail = f" ({method['description']})" if method.get("description") else ""
        lines.append(f"- Submission method: {method['value']}{detail}")

    def _bullets(header: str, items, render) -> None:
        rendered = [render(i) for i in (items or []) if isinstance(i, dict)]
        rendered = [r for r in rendered if r]
        if rendered:
            lines.append(f"- {header}:")
            lines.extend(f"    * {r}" for r in rendered)

    _bullets(
        "Page limits",
        submission.get("page_limits"),
        lambda i: f"{i.get('volume')}: {i.get('limit')}" if i.get("limit") else None,
    )
    _bullets(
        "Required volumes/sections",
        submission.get("required_volumes_or_sections"),
        lambda i: f"{i.get('name')} — {i.get('description')}" if i.get("name") else None,
    )
    _bullets(
        "Key deliverables",
        (summary.get("technical_core") or {}).get("key_deliverables"),
        lambda i: f"{i.get('title')}: {i.get('description')}" if i.get("title") else None,
    )
    # Section L: proposal-wide preparation/submission rules every section obeys.
    _bullets(
        "Instructions to offerors (Section L)",
        summary.get("instructions_to_offerors"),
        lambda i: (
            f"[{i.get('applies_to') or 'All'}] {i.get('instruction')}"
            if i.get("instruction")
            else None
        ),
    )
    return "\n".join(lines) if lines else None


def _required_volumes(summary: Optional[dict]) -> list[str]:
    """The proposal structure the RFP itself mandates (Section L), if any."""
    volumes = ((summary or {}).get("submission_requirements") or {}).get(
        "required_volumes_or_sections"
    ) or []
    return [
        f"{v.get('name')} — {v.get('description') or ''}".strip(" —")
        for v in volumes
        if isinstance(v, dict) and v.get("name")
    ]


def _evaluation_criteria(summary: Optional[dict], requirements: list[dict]) -> list[str]:
    """The Section M factors the proposal is scored on.

    Drawn from both extraction paths — the per-requirement rows categorised
    `Evaluation Criteria` and the document-level `evaluation_factors` on the
    solicitation summary — since either extractor may catch what the other misses.
    """
    criteria = [
        r["raw_text_content"]
        for r in requirements
        if r["category"] == EVALUATION_CATEGORY
    ]
    for f in (summary or {}).get("evaluation_factors") or []:
        if not isinstance(f, dict) or not f.get("factor"):
            continue
        importance = f" (importance: {f['importance']})" if f.get("importance") else ""
        criteria.append(f"{f['factor']}: {f.get('description') or ''}{importance}".strip())
    return criteria


def _call_planner(prompt: str) -> ProposalOutline:
    """Outline generation via the configured LLM provider. Isolated as a seam so
    tests can stub it (mirrors how ingestion isolates `run_extraction`)."""
    return get_llm().generate_structured(
        prompt,
        ProposalOutline,
        system=_OUTLINE_SYSTEM_PROMPT,
    )


def _plan_outline(
    rfp_id: UUID,
    requirements: list[dict],
    summary: Optional[dict] = None,
    company_context: Optional[str] = None,
) -> list[dict]:
    """Groups requirements into proposal sections via structured output.

    Only `ANSWERABLE_CATEGORIES` requirements are assigned to sections. Section L
    (`Instruction`) and Section M (`Evaluation Criteria`) rows govern *how* the
    proposal is written and scored rather than being things it answers, so they
    are surfaced to the planner as structure and scoring targets instead.
    """
    answerable = [r for r in requirements if r["category"] in ANSWERABLE_CATEGORIES]
    if not answerable:
        # Every row was classified L/M (or with an unknown category). Better a
        # generic outline over everything than no proposal at all.
        logger.warning(
            "drafting rfp=%s: no answerable requirements after filtering L/M — "
            "planning over all %d row(s) instead.",
            rfp_id,
            len(requirements),
        )
        answerable = requirements

    # Present each requirement with an integer ref; the model echoes refs (not
    # UUIDs), which we resolve back to real ids below — far less error-prone.
    listing = "\n".join(
        f"[{i}] ({r['category']}) {r['section_number']}: {r['raw_text_content']}"
        for i, r in enumerate(answerable)
    )
    criteria = _evaluation_criteria(summary, requirements)
    volumes = _required_volumes(summary)

    prompt = ""
    if volumes:
        prompt += (
            "REQUIRED PROPOSAL STRUCTURE (Section L — mirror this exactly):\n"
            + "\n".join(f"  - {v}" for v in volumes)
            + "\n\n"
        )
    else:
        prompt += (
            "REQUIRED PROPOSAL STRUCTURE: none stated — group the requirements by "
            "subject-matter theme yourself.\n\n"
        )
    if criteria:
        prompt += (
            "EVALUATION CRITERIA (Section M):\n"
            + "\n".join(f"  [{i}] {c}" for i, c in enumerate(criteria))
            + "\n\n"
        )
    if company_context:
        prompt += f"COMPANY PROFILE (source of win themes):\n{company_context}\n\n"
    prompt += f"REQUIREMENTS:\n{listing}"

    plan: Optional[ProposalOutline] = _call_planner(prompt)
    if plan is None or not plan.sections:
        raise RuntimeError("Planner returned no proposal outline.")

    n = len(answerable)
    outline: list[dict] = []
    for s in plan.sections:
        # Drop any hallucinated/out-of-range refs, then resolve to real rows.
        valid_refs = [ref for ref in s.requirement_refs if 0 <= ref < n]
        valid_criteria = [
            criteria[ref] for ref in s.evaluation_criteria_refs if 0 <= ref < len(criteria)
        ]
        outline.append(
            {
                "title": s.section_title,
                "brief": s.brief,
                "requirement_ids": [answerable[r]["requirement_id"] for r in valid_refs],
                "requirement_texts": [answerable[r]["raw_text_content"] for r in valid_refs],
                "evaluation_criteria": valid_criteria,
                "win_themes": s.win_themes,
                # 0 is the planner's "no page limit stated" signal (a required
                # int, since a schema default would break structured output).
                "target_words": s.target_words or None,
            }
        )
    logger.info(
        "drafting: planned %d section(s) for rfp %s (%s structure, %d evaluation criterion/a)",
        len(outline),
        rfp_id,
        "Section L" if volumes else "themed",
        len(criteria),
    )
    return outline


# ---------------------------------------------------------------------------
# Per-section subgraph nodes
# ---------------------------------------------------------------------------

def _draft_section_node(state: DraftingState) -> DraftingState:
    """Drafts this section, grounded in retrieved past-performance context.

    Runs on the first pass and on each critic-driven revision; `attempts` counts
    how many drafts this section has consumed and `feedback` carries the critic's
    notes into a revision.
    """
    section = state["section"]
    attempts = state["attempts"] + 1
    logger.info("drafting: section '%s' (attempt %d)", section["title"], attempts)
    # Fall back to the brief when the planner mapped no requirements to a section.
    requirement_texts = section["requirement_texts"] or [section["brief"]]
    grounded = False
    citations: list[dict] = []
    grounded_requirement_count: Optional[int] = None
    requirement_count: Optional[int] = None
    weak_grounding = False
    try:
        result = generate_section_draft(
            uploaded_by=UUID(state["uploaded_by"]),
            section_title=section["title"],
            requirement_texts=requirement_texts,
            feedback=_combined_feedback(state.get("feedback_history") or []),
            solicitation_context=state.get("sol_context"),
            company_context=state.get("company_context"),
            evaluation_criteria=section.get("evaluation_criteria"),
            win_themes=section.get("win_themes"),
            target_words=section.get("target_words"),
            retrieval_filters=state.get("retrieval_filters"),
        )
        content = result["content"]
        # Quality signal, not core data — default to "not grounded" so a writer
        # that omits it errs toward flagging the section for review.
        grounded = result.get("grounded", False)
        # Per-requirement coverage and evidence quality, when the writer reports
        # them (older/stubbed writers may not) — left None/False rather than
        # guessed, so save_section only adds a note when it actually knows.
        # `requirement_count` comes from the writer, not `len(requirement_texts)`
        # here, so it reflects what was actually drafted against (the brief
        # fallback above can diverge from `section["requirement_texts"]`).
        grounded_requirement_count = result.get("grounded_requirement_count")
        requirement_count = result.get("requirement_count")
        weak_grounding = result.get("weak_grounding", False)
        # Carried to save_section, where they become the section's confidence
        # score and citation chips. A revision replaces them, so what is stored
        # describes the attempt that was actually persisted.
        citations = result.get("citations") or []
    except DraftGuardrailError as exc:
        # Expected rejection: keep the run going; flag for human attention at save.
        logger.warning("drafting: section '%s' failed guardrail: %s", section["title"], exc)
        content = None
    except Exception:
        # Isolate any other draft-time failure (retrieval, LLM timeout, etc.) to
        # this section so one bad section can't sink the whole proposal run. It
        # is persisted empty and surfaced for a human, same as a guardrail reject.
        logger.exception("drafting: section '%s' draft failed unexpectedly", section["title"])
        content = None

    return {
        **state,
        "section": {
            **section,
            "content": content,
            "grounded": grounded,
            "grounded_requirement_count": grounded_requirement_count,
            "requirement_count": requirement_count,
            "weak_grounding": weak_grounding,
            "citations": citations,
        },
        "attempts": attempts,
    }


def _call_critic(
    section_title: str,
    requirement_texts: list[str],
    draft: str,
    evaluation_criteria: Optional[list[str]] = None,
    solicitation_context: Optional[str] = None,
    company_context: Optional[str] = None,
    citations: Optional[list[dict]] = None,
) -> ComplianceReview:
    """Structured compliance review via the LLM provider. Isolated as a seam.

    The critic is given the same frame as the writer: without the company profile
    it cannot tell an unsupported claim from a supported one, and without the
    evaluation criteria it cannot judge scoring alignment at all. `citations` are
    the actual past-performance chunks the writer was handed (source + content) —
    without them the critic can only judge plausibility against the profile
    summary, not verify that a claim traces to a specific retrieved source.
    """
    reqs = "\n".join(f"  {i + 1}. {t}" for i, t in enumerate(requirement_texts))
    sol = f"SOLICITATION CONTEXT:\n{solicitation_context}\n\n" if solicitation_context else ""
    company = f"COMPANY PROFILE (the only supportable facts):\n{company_context}\n\n" if company_context else ""
    evidence = (
        "RETRIEVED EVIDENCE CHUNKS (the only past-performance sources the writer "
        "had access to):\n"
        + "\n\n".join(
            f"[{c.get('source_name', 'unknown')} — relevance {c.get('score', 0):.2f}]\n"
            f"{c.get('content', '')}"
            for c in citations
        )
        + "\n\n"
        if citations
        else ""
    )
    criteria = (
        "EVALUATION CRITERIA:\n"
        + "\n".join(f"  - {c}" for c in evaluation_criteria)
        + "\n\n"
        if evaluation_criteria
        else ""
    )
    prompt = (
        f"{sol}"
        f"{company}"
        f"{evidence}"
        f"SECTION: {section_title}\n\n"
        f"REQUIREMENTS:\n{reqs}\n\n"
        f"{criteria}"
        f"DRAFT:\n{draft}\n\n"
        "Review the draft on all four dimensions. For each unsupported claim, say "
        "whether it fails to match the COMPANY PROFILE, the RETRIEVED EVIDENCE "
        "CHUNKS, or both — a claim consistent with either is supported."
    )
    return get_llm().generate_structured(
        prompt, ComplianceReview, system=_CRITIC_SYSTEM_PROMPT
    )


def _combined_feedback(history: list[str]) -> Optional[str]:
    """Folds every prior revision round into one instruction for the next attempt.

    A single prior round is passed through unwrapped — the common case, and the
    shape earlier callers/tests already expect. Two or more rounds are labeled by
    attempt, so a revision can see the *whole* trail of what's already been
    raised, not just the latest verdict: the writer regenerates each section from
    scratch (no incremental edit), so without this a fix in round 2 can silently
    reintroduce something round 1's feedback already resolved.
    """
    if not history:
        return None
    if len(history) == 1:
        return history[0]
    return "\n\n".join(
        f"[Revision {i + 1} feedback]\n{f}" for i, f in enumerate(history)
    )


def _review_feedback(review: ComplianceReview) -> str:
    """Folds the critic's findings into one actionable revision instruction."""
    parts = [review.feedback] if review.feedback else []
    if review.unsupported_claims:
        parts.append(
            "Remove or substantiate these unsupported claims: "
            + "; ".join(review.unsupported_claims)
        )
    if review.filler_found:
        parts.append(
            "Replace this filler with specific, evidenced content: "
            + "; ".join(review.filler_found)
        )
    if not review.evaluation_alignment:
        parts.append("Speak directly to the stated evaluation criteria.")
    if not review.benefit_mapped:
        parts.append(
            "At least one claim states a feature/proof but never the "
            "operational benefit to the government — for every substantive "
            "claim, state the benefit explicitly and tie it to a named "
            "evaluation criterion when one applies."
        )
    return "\n".join(parts)


def _check_compliance_node(state: DraftingState) -> DraftingState:
    """Critiques the current draft; sets `feedback` when a revision is warranted."""
    section = state["section"]
    content = section.get("content")
    # Nothing to review if drafting was guardrail-rejected or the section has no
    # concrete requirements to check against — proceed straight to save. No
    # critic ran against this content, so any earlier round's cited_sources is
    # now stale and must not be persisted as if it described this content.
    if not content or not section["requirement_texts"]:
        return {**state, "feedback": None, "cited_sources": None}

    try:
        review = _call_critic(
            section["title"],
            section["requirement_texts"],
            content,
            evaluation_criteria=section.get("evaluation_criteria"),
            solicitation_context=state.get("sol_context"),
            company_context=state.get("company_context"),
            citations=section.get("citations"),
        )
    except Exception:
        # A failed critic must neither sink the run nor silently pass the draft:
        # skip revision and let it through as needs_review for a human to verify.
        # Same staleness reasoning as above: this content was never reviewed.
        logger.exception(
            "drafting: compliance review failed for '%s'; saving unreviewed", section["title"]
        )
        return {**state, "feedback": None, "cited_sources": None}

    if review is None:
        return {**state, "feedback": None, "cited_sources": None}

    # Captured on both the pass and fail paths — a *passing* review still tells
    # us which evidence the final, saved draft actually leans on.
    cited_sources = list(review.cited_sources)
    if review.passes():
        return {**state, "feedback": None, "cited_sources": cited_sources}

    feedback = _review_feedback(review)
    # Convergence check: if the exact same unsupported claims/filler survived a
    # revision unchanged, the writer isn't converging on a fix — each attempt
    # regenerates the section from scratch, so a repeat here means the model is
    # circling rather than closing the gap, and the remaining budget is better
    # spent by a human than by a fourth (or however many) identical attempt.
    findings = frozenset(review.unsupported_claims) | frozenset(review.filler_found)
    stalled = bool(findings) and findings == state.get("prior_findings")
    if stalled:
        feedback += (
            "\n\n[Compliance review repeated the same finding(s) after a "
            "revision attempt — stopping early rather than spending the "
            "remaining revision budget on a fix that isn't converging.]"
        )
        logger.warning(
            "drafting: section '%s' compliance findings did not change after a "
            "revision — stopping early instead of exhausting the attempt budget.",
            section["title"],
        )
    else:
        logger.info(
            "drafting: section '%s' needs revision (addressed=%s aligned=%s "
            "unsupported=%d filler=%d) — %.80s",
            section["title"],
            review.addressed,
            review.evaluation_alignment,
            len(review.unsupported_claims),
            len(review.filler_found),
            feedback,
        )
    # `feedback` (latest only) is what save_section surfaces as review_notes when
    # the revision budget runs out — kept singular so a reviewer sees the final
    # verdict, not the accumulated trail. `feedback_history` is the trail itself,
    # threaded to the writer via `_combined_feedback` on the next attempt.
    history = (state.get("feedback_history") or []) + [feedback]
    return {
        **state,
        "feedback": feedback,
        "feedback_history": history,
        "cited_sources": cited_sources,
        "prior_findings": findings,
        "stalled": stalled,
    }


def _after_check(state: DraftingState) -> str:
    """Conditional edge: revise the section if the critic flagged gaps and budget
    remains, otherwise save it. A stalled loop (the critic's findings didn't
    change after a revision) saves immediately regardless of remaining budget —
    another identical attempt isn't going to converge either."""
    if state.get("stalled"):
        return "save"
    if state["feedback"] and state["attempts"] < _MAX_ATTEMPTS:
        return "revise"
    return "save"


def _save_section_node(state: DraftingState) -> DraftingState:
    """Persists this drafted section and records its id."""
    section = state["section"]
    content = section.get("content")
    status = "needs_review" if content else "empty"
    primary_req = section["requirement_ids"][0] if section["requirement_ids"] else None
    # If the section is saved with the critic still flagging gaps (revision budget
    # spent), keep that feedback so a reviewer sees why it needs review.
    notes = [state["feedback"]] if content and state.get("feedback") else []
    # An ungrounded section is thin for a reason a reviewer should see on the
    # section itself, not only in the run's logs.
    if content and not section.get("grounded"):
        notes.append(
            "Drafted without matching past-performance context — claims are "
            "unevidenced; verify before submission."
        )
    elif content:
        # Only reached once fully grounded (the branch above already covers the
        # zero-evidence case); requirement_count/grounded_requirement_count are
        # None for a writer that doesn't report them, so this stays silent
        # rather than guessing at partial coverage.
        req_count = section.get("requirement_count")
        grounded_count = section.get("grounded_requirement_count")
        if grounded_count is not None and req_count and grounded_count < req_count:
            notes.append(
                f"Only {grounded_count}/{req_count} requirement(s) in this section "
                "have supporting past-performance evidence — the rest may rest on "
                "unevidenced assumptions; verify before submission."
            )
        if section.get("weak_grounding"):
            notes.append(
                "Some evidence used fell below the standard relevance threshold "
                "— verify it actually supports the claim before submission."
            )
        # Only trusted when the critic explicitly reported a *non-empty* usage
        # list — an empty list is ambiguous (it means either "the critic found
        # nothing used" or "this review predates the field"), and there is no
        # way to tell those apart from the value alone, so an empty list is
        # treated as no signal rather than as "nothing was used".
        cited = state.get("cited_sources")
        if cited:
            available = set(reference_tags(section.get("citations") or []))
            unused = available - set(cited)
            if unused:
                notes.append(
                    f"Retrieved evidence from {', '.join(sorted(unused))} was "
                    "supplied but the compliance review found no claim "
                    "reflecting it — retrieval may be broader than what the "
                    "draft actually cites."
                )
    review_notes = "\n".join(notes) or None
    # The retrieval that produced this draft, recorded rather than discarded:
    # the workspace renders both, and until now got a hardcoded 0.0 and [].
    # A guardrail-rejected section has no citations, which correctly scores 0.
    citations = section.get("citations") or []
    section_id = docs.insert_proposal_section(
        proposal_id=UUID(state["proposal_id"]),
        section_title=section["title"],
        content=content or "",
        requirement_id=UUID(primary_req) if primary_req else None,
        status=status,
        review_notes=review_notes,
        confidence=grounding_confidence(citations) if content else 0.0,
        reference_tags=reference_tags(citations) if content else [],
        # Position in the planned outline (set by run_drafting when it fanned
        # out), not insertion order — sections draft concurrently, so this is
        # the only thing that preserves the outline's (Section-L-mirroring)
        # sequence once concurrent completion times are involved.
        sort_order=section.get("sort_order", 0),
    )
    return {**state, "section_id": str(section_id)}


# ---------------------------------------------------------------------------
# Graph wiring (compiled once, reused across sections and runs)
# ---------------------------------------------------------------------------

def _build_graph():
    from langgraph.graph import StateGraph, START, END

    graph = StateGraph(DraftingState)
    graph.add_node("draft_section", _draft_section_node)
    graph.add_node("check_compliance", _check_compliance_node)
    graph.add_node("save_section", _save_section_node)

    graph.add_edge(START, "draft_section")
    # draft → critic → (revise ↺ draft | save), bounded by _MAX_ATTEMPTS.
    graph.add_edge("draft_section", "check_compliance")
    graph.add_conditional_edges(
        "check_compliance", _after_check, {"revise": "draft_section", "save": "save_section"}
    )
    graph.add_edge("save_section", END)
    return graph.compile()


_drafting_graph = None


def _get_graph():
    global _drafting_graph
    if _drafting_graph is None:
        _drafting_graph = _build_graph()
    return _drafting_graph


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

async def run_drafting(proposal_id: UUID, retrieval_filters: Optional[dict] = None) -> dict:
    """Drafts one proposal. Returns a summary of saved sections.

    Addressed by **proposal**, not by RFP: sections are the proposal's own work
    product, so drafting the same solicitation for two bids has to produce two
    independent sets. The document behind it supplies the requirements.

    Loads + plans once, then fans out over sections with bounded concurrency
    (`settings.draft_max_concurrency`). Progress is tracked on
    `proposals.drafting_status`: 'drafting' → 'drafted' (or 'draft_failed').

    That flag lives on the proposal rather than on the document (migration
    0005) precisely because this function is per-proposal: two bids drafted
    from one solicitation were overwriting each other's progress, and one run's
    failure was displayed against the other. `rfp_documents.processing_status`
    now only ever describes ingestion.

    `retrieval_filters` (e.g. `{"outcome": "won"}`) narrows the knowledge-base
    search every section's retrieval runs against — see `retrieval.
    search_similar`. None (the default) applies no filter, so an ordinary
    drafting request behaves exactly as before this existed.
    """
    proposal = UUID(str(proposal_id))
    rfp = proposals_service.rfp_for_proposal_unscoped(proposal)
    proposals_service.set_drafting_status(proposal, "drafting")
    try:
        # Loading + planning are blocking (DB + one LLM call); run off the loop.
        uploaded_by, requirements, summary, profile = await asyncio.to_thread(
            _load_context, rfp
        )
        sol_context = _format_solicitation_context(summary)
        company_context = _format_company_profile(profile)
        if not company_context:
            # Without the offeror's own facts every claim is unevidenced, which is
            # exactly the generic prose the drafting prompts work to prevent.
            logger.warning(
                "drafting rfp=%s: tenant has no company profile — drafts will have "
                "no CAGE/UEI, set-aside status, certifications or past contracts to "
                "cite. Fill in the company profile to ground them.",
                rfp,
            )
        outline = await asyncio.to_thread(
            _plan_outline, rfp, requirements, summary, company_context
        )

        # Clear signal when the tenant has no past-performance to retrieve against:
        # every section will be ungrounded (generic) rather than silently so.
        grounded = await asyncio.to_thread(tenant_history_count, UUID(uploaded_by)) > 0
        if not grounded:
            logger.warning(
                "drafting rfp=%s: tenant has no past-performance (historical_chunks "
                "empty) — drafts will be ungrounded. Ingest past performance to ground them.",
                rfp,
            )

        # Compile the graph once, up front — off the fan-out — so the langgraph
        # import + compile isn't paid inside (and raced by) the first wave of
        # concurrent section invokes.
        await asyncio.to_thread(_get_graph)

        semaphore = asyncio.Semaphore(settings.draft_max_concurrency)

        async def _draft_one(outline_index: int, section: dict) -> Optional[str]:
            # Outline position, not completion order — sections draft
            # concurrently below, so insertion order alone would not preserve
            # this. Read by _save_section_node via section["sort_order"].
            section["sort_order"] = outline_index
            state: DraftingState = {
                "proposal_id": str(proposal),
                "uploaded_by": uploaded_by,
                "section": section,
                "sol_context": sol_context,
                "company_context": company_context,
                "retrieval_filters": retrieval_filters,
                "attempts": 0,
                "feedback": None,
                "feedback_history": [],
                "cited_sources": None,
                "prior_findings": None,
                "stalled": False,
                "section_id": None,
            }
            async with semaphore:
                try:
                    # LangGraph invoke is synchronous; run each section's subgraph in
                    # a worker thread so up to draft_max_concurrency overlap their calls.
                    final: DraftingState = await asyncio.to_thread(
                        _get_graph().invoke, state, {"recursion_limit": _RECURSION_LIMIT}
                    )
                except Exception:
                    # Isolate an unexpected per-section failure (e.g. the DB save)
                    # so one section can't sink the whole run; the in-node guards
                    # already absorb draft/critic errors.
                    logger.exception("drafting: section '%s' failed; skipping", section["title"])
                    return None
                return final["section_id"]

        section_ids = await asyncio.gather(
            *(_draft_one(i, s) for i, s in enumerate(outline))
        )
    except Exception as exc:
        proposals_service.set_drafting_status(
            proposal, "draft_failed", docs.failure_reason(exc)
        )
        logger.exception("drafting failed for proposal=%s rfp=%s", proposal, rfp)
        raise

    saved = [sid for sid in section_ids if sid]
    proposals_service.set_drafting_status(proposal, "drafted")
    # The agent writes sections straight to the DB, so it must evict what the
    # API cached on the tenant's behalf — the workspace polls sections while
    # drafting runs, so an empty list is cached long before the first save
    # lands. Same class of bug as the ingestion cache gap (GAP_ANALYSIS §1.3),
    # which was listed there as an unfixed follow-up for exactly this task.
    cache.cache_delete(cache.sections_key(uploaded_by, proposal))
    return {
        "proposal_id": str(proposal),
        "rfp_id": str(rfp),
        "sections": len(saved),
        "section_ids": saved,
        "grounded": grounded,
    }


def run_drafting_sync(proposal_id: UUID, retrieval_filters: Optional[dict] = None) -> dict:
    """Synchronous wrapper (for the Celery worker / step 5)."""
    return asyncio.run(run_drafting(UUID(str(proposal_id)), retrieval_filters=retrieval_filters))
