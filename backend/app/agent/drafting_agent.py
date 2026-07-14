"""Proposal drafting agent — the AI writer (Sprint 3).

A bounded LangGraph state machine that turns an RFP's extracted compliance
matrix into a full set of drafted `proposal_sections`:

    load_requirements → plan_outline
        → (draft_section → check_compliance → [revise ↺ | save_section])* → END

Each section is grounded in the tenant's past-performance context via the RAG
retriever (`draft_writer.generate_section_draft`), reviewed by a compliance
critic that can send it back for up to `_MAX_ATTEMPTS` revisions, and guardrail-
validated before it is persisted.

Design mirrors `compliance_extractor.py`: langgraph is imported lazily so this
module stays import-safe and out of the API import chain; LLM calls go through
the provider-agnostic `app.services.llm` port (telemetry lives in the adapter).
"""

import asyncio
import logging
from typing import Optional, TypedDict
from uuid import UUID

from pydantic import BaseModel, Field

from app.services import document_service as docs
from app.services.draft_writer import generate_section_draft
from app.services.guardrails import DraftGuardrailError
from app.services.llm import get_llm

logger = logging.getLogger(__name__)

_OUTLINE_SYSTEM_PROMPT = (
    "You are a lead proposal manager. Group the RFP's compliance requirements "
    "into a logical set of proposal sections (e.g. Technical Approach, Management "
    "Plan, Past Performance, Security). Assign every requirement to exactly one "
    "section by its reference number. For each section, give a short brief of what "
    "it must cover. Do not invent requirements; only use the reference numbers "
    "provided."
)
_CRITIC_SYSTEM_PROMPT = (
    "You are a government-contracts compliance reviewer. Given a proposal section "
    "draft and the requirements it must satisfy, decide whether the draft fully "
    "and verifiably addresses EVERY requirement. If anything is missing, vague, or "
    "unsupported, set addressed=false and give specific, actionable feedback naming "
    "the gaps. Be strict but fair; do not demand facts the writer cannot know."
)

# LangGraph counts every node visit against a recursion limit (default 25). The
# per-section draft→check→save loop plus revisions uses several visits per
# section, so raise the ceiling.
_RECURSION_LIMIT = 200

# Total draft attempts per section (1 initial + up to 2 critic-driven revisions).
_MAX_ATTEMPTS = 3


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
    feedback: str = Field(
        default="", description="Specific gaps to fix; empty when addressed."
    )


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------

class DraftingState(TypedDict):
    rfp_id: str
    uploaded_by: str
    requirements: list[dict]      # loaded compliance rows; list position == ref index
    outline: list[dict]           # resolved sections (title/brief/requirement_ids/texts/content)
    current_idx: int
    attempts: int                 # draft attempts spent on the current section
    feedback: Optional[str]       # critic feedback to fold into the next attempt
    saved_section_ids: list[str]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def _load_requirements_node(state: DraftingState) -> DraftingState:
    """Loads the document owner + its extracted requirements."""
    rfp_id = UUID(state["rfp_id"])
    document = docs.get_document(rfp_id)
    requirements = docs.get_requirements(rfp_id)
    if not requirements:
        raise RuntimeError(
            f"No extracted requirements for rfp {rfp_id}; run ingestion first."
        )
    logger.info("drafting: loaded %d requirement(s) for rfp %s", len(requirements), rfp_id)
    return {
        **state,
        "uploaded_by": str(document["uploaded_by"]),
        "requirements": requirements,
        "current_idx": 0,
        "attempts": 0,
        "feedback": None,
        "saved_section_ids": [],
    }


def _call_planner(listing: str) -> ProposalOutline:
    """Outline generation via the configured LLM provider. Isolated as a seam so
    tests can stub it (mirrors how ingestion isolates `run_extraction`)."""
    return get_llm().generate_structured(
        f"REQUIREMENTS:\n{listing}",
        ProposalOutline,
        system=_OUTLINE_SYSTEM_PROMPT,
    )


def _plan_outline_node(state: DraftingState) -> DraftingState:
    """Groups requirements into proposal sections via Gemini structured output."""
    requirements = state["requirements"]
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
    logger.info("drafting: planned %d section(s) for rfp %s", len(outline), state["rfp_id"])
    return {**state, "outline": outline, "current_idx": 0}


def _draft_section_node(state: DraftingState) -> DraftingState:
    """Drafts the current section, grounded in retrieved past-performance context.

    Runs on the first pass and on each critic-driven revision; `attempts` counts
    how many drafts this section has consumed and `feedback` carries the critic's
    notes into a revision.
    """
    idx = state["current_idx"]
    section = state["outline"][idx]
    attempts = state["attempts"] + 1
    logger.info(
        "drafting: section %d/%d — %s (attempt %d)",
        idx + 1,
        len(state["outline"]),
        section["title"],
        attempts,
    )
    # Fall back to the brief when the planner mapped no requirements to a section.
    requirement_texts = section["requirement_texts"] or [section["brief"]]
    try:
        result = generate_section_draft(
            uploaded_by=UUID(state["uploaded_by"]),
            section_title=section["title"],
            requirement_texts=requirement_texts,
            feedback=state.get("feedback"),
        )
        content = result["content"]
    except DraftGuardrailError as exc:
        # Keep the run going; mark the section for human attention at save time.
        logger.warning("drafting: section '%s' failed guardrail: %s", section["title"], exc)
        content = None

    outline = list(state["outline"])
    outline[idx] = {**section, "content": content}
    return {**state, "outline": outline, "attempts": attempts}


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
    idx = state["current_idx"]
    section = state["outline"][idx]
    content = section.get("content")
    # Nothing to review if drafting was guardrail-rejected or the section has no
    # concrete requirements to check against — proceed straight to save.
    if not content or not section["requirement_texts"]:
        return {**state, "feedback": None}

    review = _call_critic(section["title"], section["requirement_texts"], content)
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
    """Persists the current drafted section and advances the loop cursor."""
    idx = state["current_idx"]
    section = state["outline"][idx]
    content = section.get("content")
    status = "needs_review" if content else "empty"
    primary_req = section["requirement_ids"][0] if section["requirement_ids"] else None
    section_id = docs.insert_proposal_section(
        rfp_id=UUID(state["rfp_id"]),
        section_title=section["title"],
        content=content or "",
        requirement_id=UUID(primary_req) if primary_req else None,
        status=status,
    )
    return {
        **state,
        "current_idx": idx + 1,
        "attempts": 0,      # reset the revision budget for the next section
        "feedback": None,
        "saved_section_ids": state["saved_section_ids"] + [str(section_id)],
    }


def _has_more_sections(state: DraftingState) -> str:
    """Conditional edge: loop back for the next section, or finish."""
    return "draft" if state["current_idx"] < len(state["outline"]) else "done"


# ---------------------------------------------------------------------------
# Graph wiring (compiled once, reused)
# ---------------------------------------------------------------------------

def _build_graph():
    from langgraph.graph import StateGraph, START, END

    graph = StateGraph(DraftingState)
    graph.add_node("load_requirements", _load_requirements_node)
    graph.add_node("plan_outline", _plan_outline_node)
    graph.add_node("draft_section", _draft_section_node)
    graph.add_node("check_compliance", _check_compliance_node)
    graph.add_node("save_section", _save_section_node)

    graph.add_edge(START, "load_requirements")
    graph.add_edge("load_requirements", "plan_outline")
    graph.add_edge("plan_outline", "draft_section")
    # draft → critic → (revise ↺ draft | save), bounded by _MAX_ATTEMPTS.
    graph.add_edge("draft_section", "check_compliance")
    graph.add_conditional_edges(
        "check_compliance", _after_check, {"revise": "draft_section", "save": "save_section"}
    )
    graph.add_conditional_edges(
        "save_section", _has_more_sections, {"draft": "draft_section", "done": END}
    )
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

    Tracks progress on rfp_documents.processing_status as a post-ingestion
    lifecycle phase: 'drafting' → 'drafted' (or 'draft_failed' on error).
    """
    rfp = UUID(str(rfp_id))
    initial: DraftingState = {
        "rfp_id": str(rfp),
        "uploaded_by": "",
        "requirements": [],
        "outline": [],
        "current_idx": 0,
        "attempts": 0,
        "feedback": None,
        "saved_section_ids": [],
    }
    docs.update_status(rfp, "drafting")
    try:
        # LangGraph invoke is synchronous; bridge to the event loop like the extractor.
        final: DraftingState = await asyncio.to_thread(
            _get_graph().invoke, initial, {"recursion_limit": _RECURSION_LIMIT}
        )
    except Exception:
        docs.update_status(rfp, "draft_failed")
        logger.exception("drafting failed for rfp=%s", rfp)
        raise
    docs.update_status(rfp, "drafted")
    return {
        "rfp_id": str(rfp),
        "sections": len(final["saved_section_ids"]),
        "section_ids": final["saved_section_ids"],
    }


def run_drafting_sync(rfp_id: UUID) -> dict:
    """Synchronous wrapper (for the Celery worker / step 5)."""
    return asyncio.run(run_drafting(UUID(str(rfp_id))))
