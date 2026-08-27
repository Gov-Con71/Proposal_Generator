"""Context-aware draft writer (Story 3.5).

Compiles a requirement plus the tenant's most relevant past-performance context
into drafted proposal prose. This is the RAG generation step: retrieve (3.2) →
assemble prompt → generate. The LLM call goes through the provider-agnostic
`app.services.llm` port, so the AI platform is swappable.
"""

import hashlib
import logging
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.cache import cache_get, cache_set
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
    "CLAIM STRUCTURE — every substantive claim must chain three parts together, "
    "in one place, not scattered: (1) the FEATURE/METHOD the offeror will use, "
    "(2) the OPERATIONAL BENEFIT to the government that follows from it — "
    "explicitly tied to a named evaluation criterion when EVALUATION CRITERIA is "
    "supplied, not left implicit, (3) PROOF — the specific contract, metric, or "
    "certification from COMPANY PROFILE/PAST-PERFORMANCE CONTEXT that makes (1) "
    "credible. A claim with (1) and (3) but no stated (2) is a feature dump, not "
    "an evaluator-scored argument — do not submit it in that form.\n"
    "\n"
    "TRACEABILITY — end the paragraph or bullet that answers a numbered "
    "requirement with an inline tag citing it, e.g. '[Req 3]'. A requirement "
    "answered across multiple paragraphs may be tagged more than once; every tag "
    "must reference a requirement number actually listed below, and every "
    "requirement listed below must get at least one tag somewhere in the section.\n"
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


# A tenant with a long past-performance history would otherwise have every
# entry dumped into every section's prompt verbatim — redundant with the
# section-specific evidence separately retrieved into PAST-PERFORMANCE CONTEXT,
# and it inflates token spend without adding signal. Capped to the strongest
# entries by contract value, a reasonable proxy for evidentiary weight absent a
# per-entry embedding to rank by relevance to the section actually being drafted.
_MAX_PAST_PERFORMANCE_ENTRIES = 8


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
        entries = sorted(
            profile.past_performance, key=lambda pp: pp.value or 0, reverse=True
        )
        shown = entries[:_MAX_PAST_PERFORMANCE_ENTRIES]
        omitted = len(entries) - len(shown)
        label = f"Past performance (top {len(shown)} by value)" if omitted else "Past performance"
        lines.append(f"- {label}:")
        lines.extend(
            f"    * {pp.contract_number} — {pp.agency}, ${pp.value:,.0f}, "
            f"{pp.period}: {pp.scope}"
            for pp in shown
        )
    return "\n".join(lines) if lines else None


# A single retrieved chunk or solicitation summary is tenant-uploaded prose of
# unbounded length; capping each keeps one oversized block from crowding the
# REQUIREMENTS/feedback placed after it out of the model's attention budget.
# Not enforced on the *assembled* prompt itself — truncating that risks cutting
# off the trailing "write it now" cue — so an oversized result is only logged.
_MAX_CHUNK_CHARS = 1500
_MAX_SOLICITATION_CHARS = 4000
_PROMPT_SOFT_CEILING_CHARS = 24_000


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " …[truncated]"


# These three render the blocks shared, byte-for-byte, with the compliance
# critic's prompt (`drafting_agent._call_critic`) — same content, same header
# text, same truncation. A draft call and its critic call see the identical
# SOLICITATION CONTEXT + COMPANY PROFILE + PAST-PERFORMANCE CONTEXT text (only
# what follows differs), which is the shape a provider's prompt-prefix caching
# (Gemini's automatic caching, Vertex explicit caching) needs to ever apply —
# formatting the same content two different ways would make every call pay
# full price for identical bytes.
def format_solicitation_block(solicitation_context: str | None) -> str:
    return (
        f"SOLICITATION CONTEXT:\n{_truncate(solicitation_context, _MAX_SOLICITATION_CHARS)}\n\n"
        if solicitation_context
        else ""
    )


def format_company_block(company_context: str | None) -> str:
    return f"COMPANY PROFILE:\n{company_context}\n\n" if company_context else ""


def format_evidence_block(context: list[dict]) -> str:
    if context:
        blocks = "\n\n".join(
            f"[{c['source_name']} — relevance {c['score']:.2f}]\n"
            f"{_truncate(c['content'], _MAX_CHUNK_CHARS)}"
            for c in context
        )
    else:
        blocks = "(no matching past-performance context found)"
    return f"PAST-PERFORMANCE CONTEXT:\n{blocks}\n\n"


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
    # Document-level framing from the solicitation summary (agency, objective, …),
    # so the section reads as a response to this specific opportunity.
    sol = format_solicitation_block(solicitation_context)
    # The offeror's own verifiable facts — the source of every evidence-backed claim.
    company = format_company_block(company_context)
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
        f"\nTarget length: approximately {target_words} words."
        if target_words
        else ""
    )
    # On a revision, fold the compliance critic's feedback into the instruction.
    revision = (
        f"\nA prior draft was reviewed and found lacking. Address this feedback "
        f"specifically:\n{feedback}\n"
        if feedback
        else ""
    )
    # Background/evidence blocks (solicitation, profile, retrieved context, win
    # themes) come first — they're static per section and cheap to attend to
    # early. EVALUATION CRITERIA (Section M) is placed immediately adjacent to
    # REQUIREMENTS rather than in the background cluster: they're the same kind
    # of constraint — what this section must satisfy and what it's scored
    # against — and separating them with a WIN THEMES block would make the model
    # read the scoring rubric and the text it must satisfy as unrelated. The word
    # budget and any revision feedback stay last, immediately before the
    # generation cue: these are the constraints the draft is actually scored
    # against, and LLM attention favors content nearest the instruction that
    # triggers generation ("lost in the middle" effect) — none of this should be
    # competing for attention from the prompt's cold middle.
    prompt = (
        f"{sol}"
        f"{company}"
        f"{format_evidence_block(context)}"
        f"{themes}"
        f"PROPOSAL SECTION: {section_title}\n\n"
        f"{evaluation}"
        f"REQUIREMENTS THIS SECTION MUST SATISFY:\n{reqs}\n"
        f"{budget}"
        f"{revision}\n\n"
        "Write the section draft now."
    )
    if len(prompt) > _PROMPT_SOFT_CEILING_CHARS:
        logger.warning(
            "_assemble_section_prompt: '%s' prompt is %d chars, over the %d soft "
            "ceiling — company profile, retrieved context, or solicitation "
            "summary may be crowding out the requirements.",
            section_title,
            len(prompt),
            _PROMPT_SOFT_CEILING_CHARS,
        )
    return prompt


# Retrieved chunks below this cosine similarity are noise rather than evidence.
# The system prompt tells the model to ground every claim in what it is given, so
# handing it weak matches actively produces off-topic or hedged prose.
_MIN_CONTEXT_SCORE = 0.35

# Tried only when a requirement clears nothing at the standard floor. Some
# evidence — even a stylistically-distant match — lets the model write a
# defensible, if hedged, response instead of an admittedly-generic one; the
# caller is told the grounding is weak (`weak_grounding`) so it isn't presented
# with the same confidence as a clean match.
_FALLBACK_CONTEXT_SCORE = 0.20

# No single retrieved document may fill more than this many of the final
# context slots. A rough, source-level stand-in for MMR: true diversity
# re-ranking needs the underlying embedding vectors to measure pairwise
# similarity, which the retrieval layer doesn't expose past a scalar score —
# this instead caps by source_name, which is what the audit's actual concern
# was (5 "matches" turning out to be 5 adjacent chunks of one past proposal).
_MAX_CHUNKS_PER_SOURCE = 2

_HYDE_BATCH_SYSTEM_PROMPT = (
    "You write a short, plausible excerpt from a government contractor's "
    "past-performance narrative — the kind of prose that appears in a proposal's "
    "prior-contract write-up — for EACH numbered requirement below, as if it "
    "were true of the offeror's history. One narrative per requirement: 2-3 "
    "sentences, concrete and specific (as if naming a real contract, metric, or "
    "outcome). Do not hedge, caveat, or address the reader; write only the "
    "narrative prose itself, as though quoting a real past-performance summary. "
    "Tag each narrative with the exact index of the requirement it answers."
)


class _HydeNarrative(BaseModel):
    index: int = Field(description="The requirement's index from the numbered list, matching exactly.")
    narrative: str = Field(description="The 2-3 sentence hypothetical past-performance excerpt.")


class _HydeBatch(BaseModel):
    narratives: list[_HydeNarrative]


# The hypothetical narrative is a pure function of (section_title,
# requirement_text) — no tenant data goes into the prompt — so it's cacheable
# across retries *and* across proposals that happen to share a requirement.
# TTL comfortably covers the LLM retry/backoff window (5 retries can span
# several minutes on a rate-limited provider); it doesn't need to live much
# longer than that, since a cache miss just costs one more LLM call.
_HYDE_CACHE_TTL_SECONDS = 1800


def _hyde_cache_key(section_title: str, requirement_text: str) -> str:
    digest = hashlib.sha256(f"{section_title}\n{requirement_text}".encode()).hexdigest()
    return f"hyde:{digest[:24]}"


def _hyde_documents(section_title: str, requirement_texts: list[str]) -> list[Optional[str]]:
    """Hypothetical past-performance narratives for every requirement in a
    section — one LLM call for the whole section instead of one per requirement.

    HyDE (Hypothetical Document Embeddings): the retrieval corpus is narrative
    prose ("delivered 412 depot overhauls under W91QUZ-19-C-0042"); the query is
    imperative/regulatory ("The contractor SHALL..."). Embedding the raw
    requirement against that corpus is a register mismatch that can silently
    drop genuinely relevant chunks phrased differently — embedding a
    *hypothetical* narrative answer instead closes that gap.

    Batched because the narratives are independent of each other: a section
    with 5 requirements used to cost 5 separate round trips for no quality
    benefit, which is 5x the request-count pressure against a per-day/per-
    minute provider quota. Caching stays per-(section, requirement) — see
    `_hyde_cache_key` — so only the genuine cache misses go into the (single)
    batch request; a retry, or a requirement shared across proposals, still
    reuses whatever is already cached.

    Run on the "light" model tier (LLM_MODEL_LIGHT, falls back to the main
    model if unset): this doesn't need the main model's quality, and a rate-
    limited retry loop on the drafting call would otherwise regenerate the same
    narratives every attempt, burning quota better spent on the draft itself.

    Returns one entry per `requirement_texts`, in the same order; None where no
    narrative could be produced (a cache miss the batch call also failed to
    fill) — callers fall back to the raw requirement text as the retrieval
    query, same as before this was batched.
    """
    keys = [_hyde_cache_key(section_title, req) for req in requirement_texts]
    results: list[Optional[str]] = [cache_get(k) for k in keys]
    misses = [i for i, r in enumerate(results) if r is None]
    if not misses:
        return results

    listing = "\n".join(f"[{i}] {requirement_texts[i]}" for i in misses)
    try:
        batch = get_llm(tier="light").generate_structured(
            f"SECTION: {section_title}\nREQUIREMENTS:\n{listing}",
            _HydeBatch,
            system=_HYDE_BATCH_SYSTEM_PROMPT,
        )
        by_index = {n.index: n.narrative for n in batch.narratives}
    except Exception:
        logger.warning(
            "_hyde_documents: batch generation failed for '%s' (%d requirement(s)) "
            "— falling back to the raw requirement text for each.",
            section_title,
            len(misses),
            exc_info=True,
        )
        by_index = {}

    for i in misses:
        narrative = by_index.get(i)
        if narrative:
            cache_set(keys[i], narrative, ttl=_HYDE_CACHE_TTL_SECONDS)
        results[i] = narrative
    return results


def _diversify(hits: list[dict], top_k: int) -> list[dict]:
    """Picks the top `top_k` hits, capping how many come from one source.

    Greedy by score: a hit is skipped past `_MAX_CHUNKS_PER_SOURCE` for its
    source and parked in `overflow`; if the diversity cap leaves fewer than
    `top_k` selected (the tenant's whole corpus is thin, or one source
    genuinely dominates), the highest-scoring overflow hits backfill the rest
    rather than under-filling the context.
    """
    ranked = sorted(hits, key=lambda h: -h["score"])
    selected: list[dict] = []
    counts: dict[str, int] = {}
    overflow: list[dict] = []
    for h in ranked:
        source = h.get("source_name")
        if counts.get(source, 0) < _MAX_CHUNKS_PER_SOURCE:
            selected.append(h)
            counts[source] = counts.get(source, 0) + 1
        else:
            overflow.append(h)
        if len(selected) >= top_k:
            break
    if len(selected) < top_k:
        selected.extend(overflow[: top_k - len(selected)])
    return selected


def _retrieve_section_context(
    uploaded_by: UUID,
    section_title: str,
    requirement_texts: list[str],
    top_k: int,
    use_hyde: bool = True,
    proposal_id: UUID | None = None,
    retrieval_filters: Optional[dict] = None,
) -> tuple[list[dict], int, bool]:
    """Retrieves grounding context per requirement instead of one pooled query.

    A single query embedding built from the whole section (title + every
    requirement concatenated) centroids toward whichever requirement is longest
    or most semantically dominant — a section bundling several requirements can
    end up retrieving evidence for only one of them while the rest get none,
    even though the section-level `grounded` flag still reads True. Querying
    per requirement and unioning the (deduped, diversified) results gives every
    requirement its own shot at evidence, from more than one source.

    `retrieval_filters` (e.g. `{"industry": "...", "outcome": "won"}`) narrows
    the candidate pool before ranking — see `retrieval.search_similar`. None
    (the default) applies no filter, unchanged from before this existed.

    Returns `(context, grounded_requirement_count, weak_grounding)`: the top-
    `top_k` context blocks across all requirements; how many distinct
    requirements found *any* evidence; and whether any of it only cleared the
    relaxed fallback floor rather than the standard one.
    """
    filters = retrieval_filters or {}
    # Split the shared top_k budget across requirements (at least 2 each), so a
    # 4-requirement section doesn't get crowded out by one requirement's chunks.
    per_req_k = max(2, -(-top_k // max(1, len(requirement_texts))))
    seen: dict[str, dict] = {}
    grounded_count = 0
    weak = False
    hydes = (
        _hyde_documents(section_title, requirement_texts)
        if use_hyde
        else [None] * len(requirement_texts)
    )
    for req, hyde in zip(requirement_texts, hydes):
        query = hyde or f"{section_title}\n{req}"
        hits = search_similar(
            uploaded_by,
            query,
            top_k=per_req_k,
            min_score=_MIN_CONTEXT_SCORE,
            proposal_id=proposal_id,
            **filters,
        )
        if not hits:
            hits = search_similar(
                uploaded_by,
                query,
                top_k=per_req_k,
                min_score=_FALLBACK_CONTEXT_SCORE,
                proposal_id=proposal_id,
                **filters,
            )
            if hits:
                weak = True
        if hits:
            grounded_count += 1
        for h in hits:
            existing = seen.get(h["chunk_id"])
            if existing is None or h["score"] > existing["score"]:
                seen[h["chunk_id"]] = h
    context = _diversify(list(seen.values()), top_k)
    return context, grounded_count, weak


def grounding_confidence(citations: list[dict]) -> float:
    """How well-evidenced a draft is, in [0, 1].

    Defined narrowly and on purpose: the mean cosine similarity of the
    past-performance context actually supplied to the writer, and 0.0 when none
    was. It measures the *evidence*, not the prose — a section can be fluent,
    compliant and still score 0 here, which is precisely the case a reviewer
    needs flagged, because nothing in the tenant's history supports it.

    The compliance critic's verdict is deliberately not folded in. It is already
    surfaced on its own terms (`status`, `review_notes`), and blending two
    unrelated signals into one number would make it mean neither.
    """
    scores = [c["score"] for c in citations if c.get("score") is not None]
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 4)


def reference_tags(citations: list[dict]) -> list[str]:
    """Distinct source documents behind a draft, strongest match first.

    Deduplicated because several chunks of one past proposal cite one source,
    and the workspace renders these as one chip per source.
    """
    seen: dict[str, float] = {}
    for c in citations:
        name = (c.get("source_name") or "").strip()
        if name:
            seen[name] = max(seen.get(name, 0.0), c.get("score") or 0.0)
    return [name for name, _ in sorted(seen.items(), key=lambda kv: -kv[1])]


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
    proposal_id: UUID | None = None,
    retrieval_filters: Optional[dict] = None,
) -> dict:
    """Drafts a single proposal section grounded in the tenant's context.

    `proposal_id` scopes retrieval: the bid's own supporting documents are
    preferred and the long-term library only fills what they don't cover.
    Omitting it searches the library alone, which is the correct behaviour for
    a proposal whose user skipped the upload step.

    Like `generate_draft`, but writes one cohesive section covering several
    requirements at once — the unit the drafting agent persists.

    `feedback` steers a critic-driven revision. The remaining optional arguments
    are the section's compliance frame, supplied by the drafting agent:
    `solicitation_context` (document-level facts from the solicitation summary),
    `company_context` (the offeror's verifiable facts), `evaluation_criteria`
    (the Section M factors this section is scored on), `win_themes`, and
    `target_words` (derived from any stated page limit). `retrieval_filters`
    (e.g. `{"outcome": "won"}`) narrows the knowledge-base search before
    ranking — see `retrieval.search_similar` — and defaults to no filtering.
    """
    # Retrieve per requirement (not one pooled query) so a multi-requirement
    # section can't have its evidence dominated by whichever requirement is
    # longest — see `_retrieve_section_context`. Imported lazily (matching the
    # rest of the codebase's settings-access convention) so this module stays
    # import-order-safe with app.core.config.
    from app.core.config import settings

    context, grounded_requirement_count, weak_grounding = _retrieve_section_context(
        uploaded_by,
        section_title,
        requirement_texts,
        top_k,
        use_hyde=settings.draft_use_hyde,
        proposal_id=proposal_id,
        retrieval_filters=retrieval_filters,
    )
    if not context:
        # Clear signal: with no past-performance the draft is ungrounded (generic).
        logger.warning(
            "generate_section_draft: '%s' has no past-performance context above "
            "the relevance floor — draft will be ungrounded.",
            section_title,
        )
    elif grounded_requirement_count < len(requirement_texts):
        logger.warning(
            "generate_section_draft: '%s' — only %d/%d requirement(s) matched "
            "past-performance context; the rest will be unevidenced.",
            section_title,
            grounded_requirement_count,
            len(requirement_texts),
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
    # Everything the writer actually had to work with, for the deterministic
    # fact-check below — a cited contract number/dollar figure not found
    # anywhere in here was not something the writer was given.
    source_context = "\n".join(
        filter(
            None,
            [solicitation_context, company_context]
            + [c["content"] for c in context],
        )
    )
    draft = validate_draft(
        text,
        requirement_count=len(requirement_texts),
        require_headings=True,
        require_requirement_tags=True,
        source_context=source_context,
    )
    logger.info(
        "generate_section_draft: '%s' — %d chars from %d context block(s)",
        section_title,
        len(draft),
        len(context),
    )
    return {
        "content": draft,
        "grounded": bool(context),
        # Per-requirement coverage: `grounded` alone is section-wide and reads
        # True as soon as *any* requirement found evidence, which understates a
        # section where only 1 of 4 requirements is actually backed.
        "grounded_requirement_count": grounded_requirement_count,
        "requirement_count": len(requirement_texts),
        "weak_grounding": weak_grounding,
        # `content` rides along so the compliance critic can check claims
        # against the actual evidence text the writer saw, not just its score.
        "citations": [
            {"source_name": c["source_name"], "score": c["score"], "content": c["content"]}
            for c in context
        ],
    }


def generate_draft(
    uploaded_by: UUID,
    requirement_text: str,
    top_k: int = 5,
    retrieval_filters: Optional[dict] = None,
) -> dict:
    """Retrieves context and generates a draft. Returns the prose + citations.

    `retrieval_filters` — see `retrieval.search_similar` — defaults to no
    filtering, unchanged from before this existed.
    """
    context = search_similar(uploaded_by, requirement_text, top_k=top_k, **(retrieval_filters or {}))
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
