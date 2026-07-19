"""Context-aware draft writer (Story 3.5).

Compiles a requirement plus the tenant's most relevant past-performance context
into drafted proposal prose. This is the RAG generation step: retrieve (3.2) →
assemble prompt → generate. The LLM call goes through the provider-agnostic
`app.services.llm` port, so the AI platform is swappable.
"""

import logging
from uuid import UUID

from app.services.guardrails import validate_draft
from app.services.llm import get_llm
from app.services.retrieval import search_similar

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a senior government-contracts proposal writer. Draft a concise, "
    "compliant, professional response to the requirement below. Ground every "
    "claim in the provided past-performance context; do not invent facts, "
    "certifications, or contract numbers. If the context is insufficient, write "
    "a defensible response and note assumptions succinctly."
)


def _assemble_prompt(requirement_text: str, context: list[dict]) -> str:
    if context:
        blocks = "\n\n".join(
            f"[{c['source_name']} — relevance {c['score']:.2f}]\n{c['content']}"
            for c in context
        )
    else:
        blocks = "(no matching past-performance context found)"
    return (
        f"REQUIREMENT:\n{requirement_text}\n\n"
        f"PAST-PERFORMANCE CONTEXT:\n{blocks}\n\n"
        "Write the proposal-section draft now."
    )


_SECTION_SYSTEM_PROMPT = (
    "You are a senior government-contracts proposal writer. Draft ONE cohesive "
    "proposal section that satisfies ALL of the numbered requirements below. "
    "Ground every claim in the provided past-performance context; do not invent "
    "facts, certifications, or contract numbers. Where the context is thin, write "
    "a defensible response and flag assumptions briefly. Produce polished prose, "
    "not a restatement of the requirement list."
)


def _assemble_section_prompt(
    section_title: str,
    requirement_texts: list[str],
    context: list[dict],
    feedback: str | None = None,
    solicitation_context: str | None = None,
) -> str:
    reqs = "\n".join(f"  {i + 1}. {t}" for i, t in enumerate(requirement_texts))
    if context:
        blocks = "\n\n".join(
            f"[{c['source_name']} — relevance {c['score']:.2f}]\n{c['content']}"
            for c in context
        )
    else:
        blocks = "(no matching past-performance context found)"
    # Document-level framing from the solicitation summary (agency, objective, …),
    # so the section reads as a response to this specific opportunity.
    sol = f"SOLICITATION CONTEXT:\n{solicitation_context}\n\n" if solicitation_context else ""
    # On a revision, fold the compliance critic's feedback into the instruction.
    revision = (
        f"\n\nA prior draft was reviewed and found lacking. Address this feedback "
        f"specifically:\n{feedback}\n"
        if feedback
        else ""
    )
    return (
        f"{sol}"
        f"PROPOSAL SECTION: {section_title}\n\n"
        f"REQUIREMENTS THIS SECTION MUST SATISFY:\n{reqs}\n\n"
        f"PAST-PERFORMANCE CONTEXT:\n{blocks}"
        f"{revision}\n\n"
        "Write the section draft now."
    )


def generate_section_draft(
    uploaded_by: UUID,
    section_title: str,
    requirement_texts: list[str],
    top_k: int = 5,
    feedback: str | None = None,
    solicitation_context: str | None = None,
) -> dict:
    """Drafts a single proposal section grounded in the tenant's context.

    Like `generate_draft`, but writes one cohesive section covering several
    requirements at once — the unit the drafting agent persists. Pass `feedback`
    from the compliance critic to steer a revision, and `solicitation_context`
    (from the extracted solicitation summary) to frame the section for this RFP.
    """
    # Retrieve against the section's combined intent (title + its requirements).
    query = section_title + "\n" + "\n".join(requirement_texts)
    context = search_similar(uploaded_by, query, top_k=top_k)
    if not context:
        # Clear signal: with no past-performance the draft is ungrounded (generic).
        logger.warning(
            "generate_section_draft: '%s' has no past-performance context "
            "(historical_chunks empty for tenant?) — draft will be ungrounded.",
            section_title,
        )
    prompt = _assemble_section_prompt(
        section_title, requirement_texts, context, feedback, solicitation_context
    )

    text = get_llm().generate_text(prompt, system=_SECTION_SYSTEM_PROMPT)
    draft = validate_draft(text)
    logger.info(
        "generate_section_draft: '%s' — %d chars from %d context block(s)",
        section_title,
        len(draft),
        len(context),
    )
    return {
        "content": draft,
        "grounded": bool(context),
        "citations": [
            {"source_name": c["source_name"], "score": c["score"]} for c in context
        ],
    }


def generate_draft(uploaded_by: UUID, requirement_text: str, top_k: int = 5) -> dict:
    """Retrieves context and generates a draft. Returns the prose + citations."""
    context = search_similar(uploaded_by, requirement_text, top_k=top_k)
    prompt = _assemble_prompt(requirement_text, context)

    text = get_llm().generate_text(prompt, system=_SYSTEM_PROMPT)
    # Guardrail: reject empty/degenerate generations before they reach the DB.
    draft = validate_draft(text)
    logger.info(
        "generate_draft: produced %d chars from %d context block(s)",
        len(draft),
        len(context),
    )
    return {
        "content": draft,
        "citations": [
            {"source_name": c["source_name"], "score": c["score"]} for c in context
        ],
    }
