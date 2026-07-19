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

Design mirrors `compliance_extractor.py`: langgraph is imported lazily so this
module stays import-safe and out of the API import chain; LLM calls go through
the provider-agnostic `app.services.llm` port (telemetry lives in the adapter).
"""

import asyncio
import logging
from typing import Optional, TypedDict
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.config import settings
from app.services import document_service as docs
from app.services.draft_writer import generate_section_draft
from app.services.guardrails import DraftGuardrailError
from app.services.llm import get_llm
from app.services.retrieval import tenant_history_count

logger = logging.getLogger(__name__)

_OUTLINE_SYSTEM_PROMPT = (
    "You are a lead proposal manager building a proposal's section outline. Group "
    "the RFP's compliance requirements into MULTIPLE focused proposal sections, "
    "each covering ONE distinct subject-matter theme (e.g. Packaging & "
    "Preservation, Marking & Labeling, Quality Assurance, Security, Past "
    "Performance). "
    "Create a separate section for every major theme present in the requirements — "
    "for a substantial RFP this is typically 4-8 sections. Do NOT collapse "
    "unrelated requirements into a single broad catch-all section (e.g. one giant "
    "'Technical Approach'); split by subject so each section is narrow enough to "
    "write and review on its own, and only combine requirements that genuinely "
    "share a topic. "
    "Assign every requirement to exactly one section by its reference number. For "
    "each section, give a short brief of what it must cover. Do not invent "
    "requirements; only use the reference numbers provided."
)
_CRITIC_SYSTEM_PROMPT = (
    "You are a government-contracts compliance reviewer. Given a proposal section "
    "draft and the requirements it must satisfy, decide whether the draft fully "
    "and verifiably addresses EVERY requirement. If anything is missing, vague, or "
    "unsupported, set addressed=false and give specific, actionable feedback naming "
    "the gaps. Be strict but fair; do not demand facts the writer cannot know."
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
    brief: str = Field(description="1–2 sentences on what this section must cover.")


class ProposalOutline(BaseModel):
    sections: list[PlannedSection]


class ComplianceReview(BaseModel):
    addressed: bool = Field(
        description="True only if the draft satisfies every requirement."
    )
    # No `default`: Gemini rejects any default in a structured-output response
    # schema, and this one silently broke the critic on every run. The field is
    # required instead — the prompt tells the model to return "" when addressed.
    feedback: str = Field(
        description="Specific gaps to fix; empty string when fully addressed."
    )


# ---------------------------------------------------------------------------
# Per-section graph state
# ---------------------------------------------------------------------------

class DraftingState(TypedDict):
    rfp_id: str
    uploaded_by: str
    section: dict                 # one resolved section (title/brief/requirement_ids/texts/content)
    sol_context: Optional[str]    # document-level framing from the solicitation summary
    attempts: int                 # draft attempts spent on this section
    feedback: Optional[str]       # critic feedback to fold into the next attempt
    section_id: Optional[str]     # id of the persisted section, set by save_section


# ---------------------------------------------------------------------------
# Loading + planning (run once, up front)
# ---------------------------------------------------------------------------

def _load_context(rfp_id: UUID) -> tuple[str, list[dict], Optional[dict]]:
    """Loads the document owner, its extracted requirements, and (if present) the
    extracted solicitation summary that frames the whole opportunity."""
    document = docs.get_document(rfp_id)
    requirements = docs.get_requirements(rfp_id)
    if not requirements:
        raise RuntimeError(
            f"No extracted requirements for rfp {rfp_id}; run ingestion first."
        )
    summary = docs.get_solicitation_summary(rfp_id)
    logger.info("drafting: loaded %d requirement(s) for rfp %s", len(requirements), rfp_id)
    return str(document["uploaded_by"]), requirements, summary


def _format_solicitation_context(summary: Optional[dict]) -> Optional[str]:
    """Condenses the solicitation summary into a short framing block for the
    drafting prompts. Returns None when nothing usable was extracted."""
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
    ]
    lines = [f"- {label}: {value}" for label, value in fields if value]
    return "\n".join(lines) if lines else None


def _call_planner(listing: str) -> ProposalOutline:
    """Outline generation via the configured LLM provider. Isolated as a seam so
    tests can stub it (mirrors how ingestion isolates `run_extraction`)."""
    return get_llm().generate_structured(
        f"REQUIREMENTS:\n{listing}",
        ProposalOutline,
        system=_OUTLINE_SYSTEM_PROMPT,
    )


def _plan_outline(rfp_id: UUID, requirements: list[dict]) -> list[dict]:
    """Groups requirements into proposal sections via Gemini structured output."""
    # Present each requirement with an integer ref; the model echoes refs (not
    # UUIDs), which we resolve back to real ids below — far less error-prone.
    listing = "\n".join(
        f"[{i}] ({r['category']}) {r['section_number']}: {r['raw_text_content']}"
        for i, r in enumerate(requirements)
    )

    plan: Optional[ProposalOutline] = _call_planner(listing)
    if plan is None or not plan.sections:
        raise RuntimeError("Planner returned no proposal outline.")

    n = len(requirements)
    outline: list[dict] = []
    for s in plan.sections:
        # Drop any hallucinated/out-of-range refs, then resolve to real rows.
        valid_refs = [ref for ref in s.requirement_refs if 0 <= ref < n]
        outline.append(
            {
                "title": s.section_title,
                "brief": s.brief,
                "requirement_ids": [requirements[r]["requirement_id"] for r in valid_refs],
                "requirement_texts": [requirements[r]["raw_text_content"] for r in valid_refs],
            }
        )
    logger.info("drafting: planned %d section(s) for rfp %s", len(outline), rfp_id)
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
    try:
        result = generate_section_draft(
            uploaded_by=UUID(state["uploaded_by"]),
            section_title=section["title"],
            requirement_texts=requirement_texts,
            feedback=state.get("feedback"),
            solicitation_context=state.get("sol_context"),
        )
        content = result["content"]
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

    return {**state, "section": {**section, "content": content}, "attempts": attempts}


def _call_critic(
    section_title: str, requirement_texts: list[str], draft: str
) -> ComplianceReview:
    """Structured compliance review via the LLM provider. Isolated as a seam."""
    reqs = "\n".join(f"  {i + 1}. {t}" for i, t in enumerate(requirement_texts))
    prompt = (
        f"SECTION: {section_title}\n\n"
        f"REQUIREMENTS:\n{reqs}\n\n"
        f"DRAFT:\n{draft}\n\n"
        "Review the draft against the requirements."
    )
    return get_llm().generate_structured(
        prompt, ComplianceReview, system=_CRITIC_SYSTEM_PROMPT
    )


def _check_compliance_node(state: DraftingState) -> DraftingState:
    """Critiques the current draft; sets `feedback` when a revision is warranted."""
    section = state["section"]
    content = section.get("content")
    # Nothing to review if drafting was guardrail-rejected or the section has no
    # concrete requirements to check against — proceed straight to save.
    if not content or not section["requirement_texts"]:
        return {**state, "feedback": None}

    try:
        review = _call_critic(section["title"], section["requirement_texts"], content)
    except Exception:
        # A failed critic must neither sink the run nor silently pass the draft:
        # skip revision and let it through as needs_review for a human to verify.
        logger.exception(
            "drafting: compliance review failed for '%s'; saving unreviewed", section["title"]
        )
        return {**state, "feedback": None}
    if review is None or review.addressed:
        return {**state, "feedback": None}
    logger.info(
        "drafting: section '%s' needs revision — %.80s", section["title"], review.feedback
    )
    return {**state, "feedback": review.feedback}


def _after_check(state: DraftingState) -> str:
    """Conditional edge: revise the section if the critic flagged gaps and budget
    remains, otherwise save it."""
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
    review_notes = state.get("feedback") if content else None
    section_id = docs.insert_proposal_section(
        rfp_id=UUID(state["rfp_id"]),
        section_title=section["title"],
        content=content or "",
        requirement_id=UUID(primary_req) if primary_req else None,
        status=status,
        review_notes=review_notes,
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

async def run_drafting(rfp_id: UUID) -> dict:
    """Drafts a full proposal for one RFP. Returns a summary of saved sections.

    Loads + plans once, then fans out over sections with bounded concurrency
    (`settings.draft_max_concurrency`). Tracks progress on rfp_documents.processing_status as a
    post-ingestion lifecycle phase: 'drafting' → 'drafted' (or 'draft_failed').
    """
    rfp = UUID(str(rfp_id))
    docs.update_status(rfp, "drafting")
    try:
        # Loading + planning are blocking (DB + one LLM call); run off the loop.
        uploaded_by, requirements, summary = await asyncio.to_thread(_load_context, rfp)
        outline = await asyncio.to_thread(_plan_outline, rfp, requirements)
        sol_context = _format_solicitation_context(summary)

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

        async def _draft_one(section: dict) -> Optional[str]:
            state: DraftingState = {
                "rfp_id": str(rfp),
                "uploaded_by": uploaded_by,
                "section": section,
                "sol_context": sol_context,
                "attempts": 0,
                "feedback": None,
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

        section_ids = await asyncio.gather(*(_draft_one(s) for s in outline))
    except Exception:
        docs.update_status(rfp, "draft_failed")
        logger.exception("drafting failed for rfp=%s", rfp)
        raise

    saved = [sid for sid in section_ids if sid]
    docs.update_status(rfp, "drafted")
    return {
        "rfp_id": str(rfp),
        "sections": len(saved),
        "section_ids": saved,
        "grounded": grounded,
    }


def run_drafting_sync(rfp_id: UUID) -> dict:
    """Synchronous wrapper (for the Celery worker / step 5)."""
    return asyncio.run(run_drafting(UUID(str(rfp_id))))
