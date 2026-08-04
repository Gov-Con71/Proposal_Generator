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


# Encodes the GovCon drafting spec: compliance-first, evidence-backed, and
# explicitly hostile to the corporate filler an unconstrained model defaults to.
_SECTION_SYSTEM_PROMPT = (
    "You are a senior government-contracts proposal writer and capture manager. "
    "Draft ONE proposal section that satisfies ALL of the numbered requirements "
    "below and scores well against the stated evaluation criteria.\n"
    "\n"
    "STRUCTURE — use these markdown headings, omitting any that the section's "
    "requirements do not support:\n"
    "  ## Understanding of the Requirement\n"
    "  ## Technical Approach\n"
    "  ## Management Plan\n"
    "  ## Differentiators\n"
    "Use bullet lists for discrete capabilities, deliverables, and controls; use "
    "prose for reasoning and approach.\n"
    "\n"
    "EVIDENCE — every capability claim must be traceable to a fact in the COMPANY "
    "PROFILE or PAST-PERFORMANCE CONTEXT provided: name the contract, agency, "
    "certification, clearance level, or metric that backs it. Do NOT invent facts, "
    "certifications, contract numbers, customer names, or performance metrics. If "
    "the supplied context does not support a claim, either drop the claim or state "
    "the assumption explicitly in one clause.\n"
    "\n"
    "TONE — active voice, authoritative, objective, specific. Write what the "
    "offeror will do and how it will be verified.\n"
    "\n"
    "PROHIBITED — never use: 'world-class', 'best-in-class', 'industry-leading', "
    "'cutting-edge', 'state-of-the-art', 'seamless', 'leverage synergies', "
    "'robust solution', 'passion for excellence', 'trusted partner'. Do not open "
    "with a company-boilerplate paragraph. Do not restate the requirement text "
    "back as prose — answer it. Do not emit placeholders such as [INSERT], TBD, "
    "or XXX; if a fact is unavailable, write the assumption instead.\n"
    "\n"
    "Output the section body only — no preamble, no closing summary of what you "
    "just wrote."
)


def _format_company_profile(profile) -> str | None:
    """Condenses the tenant's company profile into a prompt block.

    This is the offeror's factual base — CAGE/UEI, set-aside status, clearances,
    certifications and prior contracts. Without it the model has no concrete
    evidence to cite and falls back on generic corporate claims, so the block is
    kept compact but complete. Returns None when the profile is empty (a tenant
    who has never filled it in), so the prompt carries no hollow header.
    """
    if profile is None:
        return None

    fields = [
        ("Legal name", profile.legal_name),
        ("CAGE code", profile.cage_code),
        ("UEI", profile.uei_number),
        ("DUNS", profile.duns_number),
        ("NAICS", " ".join(x for x in (profile.naics_code, profile.naics_description) if x)),
        ("Set-aside / socio-economic status", ", ".join(profile.socio_economic_status)),
        ("CMMC level", profile.cmmc_level),
        ("Certifications", ", ".join(profile.certifications)),
        ("Facility/personnel clearance", profile.security_clearance),
        ("Capabilities", profile.capabilities_overview),
    ]
    lines = [f"- {label}: {value}" for label, value in fields if value]

    if profile.past_performance:
        lines.append("- Past performance:")
        lines.extend(
            f"    * {pp.contract_number} — {pp.agency}, ${pp.value:,.0f}, "
            f"{pp.period}: {pp.scope}"
            for pp in profile.past_performance
        )
    return "\n".join(lines) if lines else None


def _assemble_section_prompt(
    section_title: str,
    requirement_texts: list[str],
    context: list[dict],
    feedback: str | None = None,
    solicitation_context: str | None = None,
    company_context: str | None = None,
    evaluation_criteria: list[str] | None = None,
    win_themes: list[str] | None = None,
    target_words: int | None = None,
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
    # The offeror's own verifiable facts — the source of every evidence-backed claim.
    company = f"COMPANY PROFILE:\n{company_context}\n\n" if company_context else ""
    # Section M: what this section is actually scored on.
    evaluation = (
        "EVALUATION CRITERIA THIS SECTION IS SCORED ON:\n"
        + "\n".join(f"  - {c}" for c in evaluation_criteria)
        + "\n\n"
        if evaluation_criteria
        else ""
    )
    themes = (
        "WIN THEMES TO CARRY THROUGH THIS SECTION:\n"
        + "\n".join(f"  - {t}" for t in win_themes)
        + "\n\n"
        if win_themes
        else ""
    )
    budget = (
        f"\n\nTarget length: approximately {target_words} words."
        if target_words
        else ""
    )
    # On a revision, fold the compliance critic's feedback into the instruction.
    revision = (
        f"\n\nA prior draft was reviewed and found lacking. Address this feedback "
        f"specifically:\n{feedback}\n"
        if feedback
        else ""
    )
    return (
        f"{sol}"
        f"{company}"
        f"PROPOSAL SECTION: {section_title}\n\n"
        f"REQUIREMENTS THIS SECTION MUST SATISFY:\n{reqs}\n\n"
        f"{evaluation}"
        f"{themes}"
        f"PAST-PERFORMANCE CONTEXT:\n{blocks}"
        f"{budget}"
        f"{revision}\n\n"
        "Write the section draft now."
    )


# Retrieved chunks below this cosine similarity are noise rather than evidence.
# The system prompt tells the model to ground every claim in what it is given, so
# handing it weak matches actively produces off-topic or hedged prose.
_MIN_CONTEXT_SCORE = 0.35


def generate_section_draft(
    uploaded_by: UUID,
    section_title: str,
    requirement_texts: list[str],
    top_k: int = 5,
    feedback: str | None = None,
    solicitation_context: str | None = None,
    company_context: str | None = None,
    evaluation_criteria: list[str] | None = None,
    win_themes: list[str] | None = None,
    target_words: int | None = None,
) -> dict:
    """Drafts a single proposal section grounded in the tenant's context.

    Like `generate_draft`, but writes one cohesive section covering several
    requirements at once — the unit the drafting agent persists.

    `feedback` steers a critic-driven revision. The remaining optional arguments
    are the section's compliance frame, supplied by the drafting agent:
    `solicitation_context` (document-level facts from the solicitation summary),
    `company_context` (the offeror's verifiable facts), `evaluation_criteria`
    (the Section M factors this section is scored on), `win_themes`, and
    `target_words` (derived from any stated page limit).
    """
    # Retrieve against the section's combined intent (title + its requirements).
    query = section_title + "\n" + "\n".join(requirement_texts)
    context = search_similar(
        uploaded_by, query, top_k=top_k, min_score=_MIN_CONTEXT_SCORE
    )
    if not context:
        # Clear signal: with no past-performance the draft is ungrounded (generic).
        logger.warning(
            "generate_section_draft: '%s' has no past-performance context above "
            "the relevance floor — draft will be ungrounded.",
            section_title,
        )
    prompt = _assemble_section_prompt(
        section_title,
        requirement_texts,
        context,
        feedback,
        solicitation_context,
        company_context,
        evaluation_criteria,
        win_themes,
        target_words,
    )

    text = get_llm().generate_text(prompt, system=_SECTION_SYSTEM_PROMPT)
    draft = validate_draft(text, requirement_count=len(requirement_texts))
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
