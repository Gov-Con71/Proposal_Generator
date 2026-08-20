"""Unit tests for the section draft writer's prompt assembly and profile block.

Pure unit tests: no DB, no vector store, no LLM. They pin down the contract the
drafting agent depends on — that every fact it threads through actually reaches
the model — because a silently dropped block produces plausible-looking but
generic prose rather than an error.
"""

import pytest

from app.models.contract import CompanyProfile, PastPerformance
from app.services.draft_writer import (
    _SECTION_SYSTEM_PROMPT,
    _assemble_section_prompt,
    _format_company_profile,
    grounding_confidence,
    reference_tags,
)


def _profile(**overrides) -> CompanyProfile:
    data = {
        "id": "11111111-1111-1111-1111-111111111111",
        "legal_name": "Acme Federal LLC",
        "cage_code": "7X9Q2",
        "uei_number": "ABC123DEF456",
        "naics_code": "541512",
        "naics_description": "Computer Systems Design",
        "socio_economic_status": ["SDVOSB", "8(a)"],
        "cmmc_level": "Level 2",
        "certifications": ["ISO 9001:2015"],
        "security_clearance": "Top Secret facility clearance",
        "capabilities_overview": "Depot maintenance and logistics.",
        "past_performance": [
            PastPerformance(
                id="pp1",
                contract_number="W91QUZ-19-C-0042",
                agency="US Army",
                value=4_200_000.0,
                scope="Depot-level widget overhaul",
                period="2019-2023",
            )
        ],
        "updated_at": "2026-01-01T00:00:00Z",
    }
    data.update(overrides)
    return CompanyProfile(**data)


# --- the company profile block ---------------------------------------------

def test_company_profile_block_carries_the_citable_facts():
    block = _format_company_profile(_profile())

    for fact in (
        "Acme Federal LLC",
        "7X9Q2",            # CAGE
        "ABC123DEF456",     # UEI
        "541512",
        "SDVOSB",
        "Level 2",
        "ISO 9001:2015",
        "Top Secret facility clearance",
    ):
        assert fact in block, f"{fact!r} missing from the company profile block"

    # Past performance carries the details that make a claim verifiable.
    assert "W91QUZ-19-C-0042" in block
    assert "US Army" in block
    assert "$4,200,000" in block
    assert "2019-2023" in block


def test_empty_profile_yields_no_block():
    """A tenant who never filled the profile in must not get a hollow header —
    an empty COMPANY PROFILE section would read to the model as 'no facts exist'
    dressed up as data."""
    assert _format_company_profile(None) is None
    empty = CompanyProfile(id="x", updated_at="2026-01-01T00:00:00Z")
    assert _format_company_profile(empty) is None


def test_profile_block_omits_fields_the_tenant_left_blank():
    block = _format_company_profile(_profile(cage_code="", certifications=[]))
    assert "CAGE" not in block
    assert "Certifications" not in block
    assert "ABC123DEF456" in block  # the populated fields still come through


def test_profile_block_caps_past_performance_to_the_strongest_entries():
    """A tenant with a long history must not have every entry dumped into every
    section's prompt — it's redundant with the section-specific evidence
    separately retrieved, and inflates token spend without adding signal."""
    from app.services.draft_writer import _MAX_PAST_PERFORMANCE_ENTRIES

    many = [
        PastPerformance(
            id=f"pp{i}",
            contract_number=f"CN-{i:04d}",
            agency="US Army",
            value=float(i),  # ascending, so the strongest (highest-value) is last
            scope="Widget work",
            period="2020-2024",
        )
        for i in range(_MAX_PAST_PERFORMANCE_ENTRIES + 5)
    ]
    block = _format_company_profile(_profile(past_performance=many))

    assert block.count("CN-") == _MAX_PAST_PERFORMANCE_ENTRIES
    # The strongest (highest-value) entries are the ones kept, not the first N.
    assert "CN-0000" not in block  # weakest, dropped
    assert f"CN-{len(many) - 1:04d}" in block  # strongest, kept
    assert f"top {_MAX_PAST_PERFORMANCE_ENTRIES} by value" in block


# --- the assembled section prompt ------------------------------------------

def test_section_prompt_carries_every_part_of_the_compliance_frame():
    prompt = _assemble_section_prompt(
        section_title="Volume I — Technical",
        requirement_texts=["The contractor SHALL deliver widgets."],
        context=[{"source_name": "past.pdf", "content": "Prior widget work.", "score": 0.81}],
        feedback="Cite a specific past contract.",
        solicitation_context="- Agency: US Army\n- Proposal due: 2026-09-01",
        company_context=_format_company_profile(_profile()),
        evaluation_criteria=["Technical merit is more important than price."],
        win_themes=["Incumbent on W91QUZ-19-C-0042"],
        target_words=1500,
    )

    assert "Volume I — Technical" in prompt
    assert "The contractor SHALL deliver widgets." in prompt
    assert "US Army" in prompt
    assert "7X9Q2" in prompt                                    # profile
    assert "Technical merit is more important" in prompt        # Section M
    assert "Incumbent on W91QUZ-19-C-0042" in prompt            # win theme
    assert "1500 words" in prompt                               # page-limit budget
    assert "Cite a specific past contract." in prompt           # revision feedback
    assert "past.pdf" in prompt                                 # retrieved evidence


def test_section_prompt_puts_requirements_and_feedback_closest_to_the_write_cue():
    """LLM attention favors content near the start and near the trailing
    instruction that triggers generation ('lost in the middle' otherwise).
    REQUIREMENTS is what the draft is actually scored against and CRITIC
    FEEDBACK is the most decision-critical instruction on a revision — both
    must sit closer to 'Write the section draft now.' than the static
    background blocks (solicitation, profile, retrieved evidence, win themes)."""
    prompt = _assemble_section_prompt(
        section_title="Volume I — Technical",
        requirement_texts=["The contractor SHALL deliver widgets."],
        context=[{"source_name": "past.pdf", "content": "Prior widget work.", "score": 0.81}],
        feedback="Cite a specific past contract.",
        solicitation_context="- Agency: US Army",
        company_context=_format_company_profile(_profile()),
        evaluation_criteria=["Technical merit is more important than price."],
        win_themes=["Incumbent on W91QUZ-19-C-0042"],
    )

    positions = {
        name: prompt.index(marker)
        for name, marker in [
            ("solicitation", "SOLICITATION CONTEXT"),
            ("company", "COMPANY PROFILE"),
            ("evidence", "PAST-PERFORMANCE CONTEXT"),
            ("themes", "WIN THEMES"),
            ("criteria", "EVALUATION CRITERIA"),
            ("requirements", "REQUIREMENTS THIS SECTION MUST SATISFY"),
            ("feedback", "A prior draft was reviewed"),
            ("cue", "Write the section draft now."),
        ]
    }

    assert positions["solicitation"] < positions["evidence"]
    assert positions["company"] < positions["evidence"]
    assert positions["evidence"] < positions["requirements"]
    assert positions["themes"] < positions["criteria"]
    assert positions["criteria"] < positions["requirements"]
    assert positions["requirements"] < positions["feedback"] < positions["cue"]


def test_section_prompt_co_locates_evaluation_criteria_with_requirements():
    """Section M (what the section is scored on) and REQUIREMENTS (what it must
    satisfy) are the same kind of constraint and must read as one adjacent
    unit — not split apart by a WIN THEMES block, which is lower-stakes
    creative input, not a hard compliance constraint."""
    prompt = _assemble_section_prompt(
        section_title="Volume I — Technical",
        requirement_texts=["The contractor SHALL deliver widgets."],
        context=[],
        evaluation_criteria=["Technical merit is more important than price."],
        win_themes=["Incumbent on W91QUZ-19-C-0042"],
    )

    between = prompt[
        prompt.index("EVALUATION CRITERIA") : prompt.index("REQUIREMENTS THIS SECTION")
    ]
    assert "WIN THEMES" not in between


def test_section_prompt_truncates_an_oversized_chunk():
    """One huge retrieved chunk must not crowd the requirements/feedback placed
    after it out of the model's attention budget."""
    from app.services.draft_writer import _MAX_CHUNK_CHARS

    huge = "X" * (_MAX_CHUNK_CHARS + 500)
    prompt = _assemble_section_prompt(
        section_title="Technical Approach",
        requirement_texts=["Do the thing."],
        context=[{"source_name": "past.pdf", "content": huge, "score": 0.9}],
    )
    assert "X" * (_MAX_CHUNK_CHARS + 1) not in prompt
    assert "…[truncated]" in prompt
    assert "REQUIREMENTS THIS SECTION MUST SATISFY" in prompt  # still present, not pushed out


def test_section_prompt_truncates_an_oversized_solicitation_context():
    from app.services.draft_writer import _MAX_SOLICITATION_CHARS

    huge = "- Agency: US Army\n" * 500
    assert len(huge) > _MAX_SOLICITATION_CHARS
    prompt = _assemble_section_prompt(
        section_title="Technical Approach",
        requirement_texts=["Do the thing."],
        context=[],
        solicitation_context=huge,
    )
    assert "…[truncated]" in prompt
    assert len(prompt) < len(huge) + 2000  # not the full untruncated block


def test_section_prompt_omits_headers_for_absent_context():
    """Optional blocks must vanish entirely when unset. A bare 'COMPANY PROFILE:'
    with nothing under it invites the model to invent what belongs there."""
    prompt = _assemble_section_prompt(
        section_title="Technical Approach",
        requirement_texts=["Do the thing."],
        context=[],
    )

    assert "COMPANY PROFILE" not in prompt
    assert "EVALUATION CRITERIA" not in prompt
    assert "WIN THEMES" not in prompt
    assert "SOLICITATION CONTEXT" not in prompt
    assert "words." not in prompt
    assert "no matching past-performance context found" in prompt


def test_system_prompt_encodes_the_govcon_drafting_spec():
    """The section system prompt is the only thing standing between the model and
    generic corporate prose, so its load-bearing instructions are pinned here."""
    # Standard federal proposal structure.
    for heading in (
        "Understanding of the Requirement",
        "Technical Approach",
        "Management Plan",
        "Differentiators",
    ):
        assert heading in _SECTION_SYSTEM_PROMPT

    # Evidence discipline and the anti-fluff constraints.
    assert "Do NOT invent facts" in _SECTION_SYSTEM_PROMPT
    assert "world-class" in _SECTION_SYSTEM_PROMPT
    assert "industry-leading" in _SECTION_SYSTEM_PROMPT
    assert "[INSERT]" in _SECTION_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Retrieval grounding (migration 0007): what the workspace actually renders
# ---------------------------------------------------------------------------

def test_confidence_is_the_mean_similarity_of_the_supplied_evidence():
    citations = [{"source_name": "a.pdf", "score": 0.9}, {"source_name": "b.pdf", "score": 0.5}]
    assert grounding_confidence(citations) == 0.7


def test_confidence_is_zero_without_evidence():
    """An ungrounded draft scores 0 — the case a reviewer most needs flagged.

    It is not a missing value: the section may read perfectly well and still
    have nothing in the tenant's history supporting a word of it.
    """
    assert grounding_confidence([]) == 0.0


def test_reference_tags_deduplicate_sources_strongest_first():
    """Several chunks of one past proposal cite one source; the UI shows chips."""
    citations = [
        {"source_name": "past_bid.pdf", "score": 0.4},
        {"source_name": "capability.docx", "score": 0.8},
        {"source_name": "past_bid.pdf", "score": 0.6},  # same source, better chunk
    ]
    assert reference_tags(citations) == ["capability.docx", "past_bid.pdf"]


def test_reference_tags_ignore_unnamed_sources():
    assert reference_tags([{"source_name": "", "score": 0.9}, {"score": 0.8}]) == []


# ---------------------------------------------------------------------------
# _retrieve_section_context: per-requirement retrieval + adaptive floor
# ---------------------------------------------------------------------------

def test_retrieve_section_context_queries_each_requirement_separately(monkeypatch):
    """A single pooled query centroids toward whichever requirement is longest;
    querying per requirement gives each one its own shot at evidence."""
    import app.services.draft_writer as _dw

    queries_seen: list[str] = []

    def fake_search(uploaded_by, query, top_k, min_score, **kwargs):
        queries_seen.append(query)
        if "staffing" in query:
            return [{"chunk_id": "staff-1", "source_name": "s.pdf", "content": "c", "score": 0.9}]
        if "security" in query:
            return [{"chunk_id": "sec-1", "source_name": "sec.pdf", "content": "c", "score": 0.8}]
        return []

    monkeypatch.setattr(_dw, "search_similar", fake_search)

    context, grounded_count, weak = _dw._retrieve_section_context(
        uploaded_by="u",
        section_title="Technical Approach",
        requirement_texts=[
            "The contractor SHALL provide staffing plans.",
            "The contractor SHALL implement security controls.",
        ],
        top_k=5,
        use_hyde=False,
    )

    assert len(queries_seen) == 2  # one retrieval call per requirement
    assert grounded_count == 2    # both requirements found evidence
    assert not weak
    assert {c["chunk_id"] for c in context} == {"staff-1", "sec-1"}


def test_retrieve_section_context_dedupes_across_requirements(monkeypatch):
    """Two requirements matching the same chunk must not double-count it."""
    import app.services.draft_writer as _dw

    def fake_search(uploaded_by, query, top_k, min_score, **kwargs):
        return [{"chunk_id": "shared", "source_name": "s.pdf", "content": "c", "score": 0.7}]

    monkeypatch.setattr(_dw, "search_similar", fake_search)

    context, grounded_count, weak = _dw._retrieve_section_context(
        uploaded_by="u",
        section_title="Technical Approach",
        requirement_texts=["Requirement A.", "Requirement B."],
        top_k=5,
        use_hyde=False,
    )

    assert len(context) == 1
    assert grounded_count == 2  # both requirements matched, even though it's one chunk


def test_retrieve_section_context_falls_back_to_a_relaxed_floor(monkeypatch):
    """A requirement with nothing above the standard floor gets one more try at
    a relaxed floor rather than being left with zero evidence outright."""
    import app.services.draft_writer as _dw

    def fake_search(uploaded_by, query, top_k, min_score, **kwargs):
        if min_score == _dw._MIN_CONTEXT_SCORE:
            return []
        assert min_score == _dw._FALLBACK_CONTEXT_SCORE
        return [{"chunk_id": "weak-1", "source_name": "w.pdf", "content": "c", "score": 0.25}]

    monkeypatch.setattr(_dw, "search_similar", fake_search)

    context, grounded_count, weak = _dw._retrieve_section_context(
        uploaded_by="u",
        section_title="Technical Approach",
        requirement_texts=["Requirement A."],
        top_k=5,
        use_hyde=False,
    )

    assert grounded_count == 1
    assert weak is True
    assert context[0]["chunk_id"] == "weak-1"


def test_retrieve_section_context_reports_partial_coverage(monkeypatch):
    """When one requirement finds nothing at either floor, the coverage count
    must reflect that rather than reporting the section as fully grounded."""
    import app.services.draft_writer as _dw

    def fake_search(uploaded_by, query, top_k, min_score, **kwargs):
        if "findable" in query:
            return [{"chunk_id": "hit", "source_name": "s.pdf", "content": "c", "score": 0.8}]
        return []

    monkeypatch.setattr(_dw, "search_similar", fake_search)

    context, grounded_count, weak = _dw._retrieve_section_context(
        uploaded_by="u",
        section_title="Technical Approach",
        requirement_texts=["A findable requirement.", "An unmatched requirement."],
        top_k=5,
        use_hyde=False,
    )

    assert grounded_count == 1
    assert len(context) == 1
    assert weak is False  # the one hit came from the standard floor, not the fallback


def test_retrieve_section_context_uses_the_hyde_document_as_the_query(monkeypatch):
    """With HyDE enabled, the query embedded must be the hypothetical narrative,
    not the raw imperative requirement text — that's the whole point: closing
    the register gap against the narrative prose the corpus is written in."""
    import app.services.draft_writer as _dw

    monkeypatch.setattr(
        _dw,
        "get_llm",
        lambda tier="default": _FakeProvider(
            "We delivered 412 depot overhauls on schedule under W91QUZ-19-C-0042."
        ),
    )

    queries_seen: list[str] = []

    def fake_search(uploaded_by, query, top_k, min_score, **kwargs):
        queries_seen.append(query)
        return [{"chunk_id": "c1", "source_name": "s.pdf", "content": "c", "score": 0.8}]

    monkeypatch.setattr(_dw, "search_similar", fake_search)

    _dw._retrieve_section_context(
        uploaded_by="u",
        section_title="Technical Approach",
        requirement_texts=["The contractor SHALL deliver widgets."],
        top_k=5,
        use_hyde=True,
    )

    assert queries_seen == ["We delivered 412 depot overhauls on schedule under W91QUZ-19-C-0042."]


def test_hyde_document_is_cached_across_calls(monkeypatch):
    """A rate-limited retry loop must not regenerate — and re-spend quota on —
    the same hypothetical narrative every attempt; the second call for the same
    (section, requirement) pair should be a cache hit, not a second LLM call."""
    import app.services.draft_writer as _dw

    calls = {"n": 0}

    class _CountingProvider:
        def generate_text(self, prompt, system=None):
            calls["n"] += 1
            return "We delivered 412 depot overhauls under W91QUZ-19-C-0042."

    monkeypatch.setattr(_dw, "get_llm", lambda tier="default": _CountingProvider())

    first = _dw._hyde_document("Technical Approach", "The contractor SHALL deliver widgets.")
    second = _dw._hyde_document("Technical Approach", "The contractor SHALL deliver widgets.")

    assert first == second == "We delivered 412 depot overhauls under W91QUZ-19-C-0042."
    assert calls["n"] == 1  # second call was a cache hit


def test_hyde_document_cache_key_is_specific_to_the_pair(monkeypatch):
    """A different requirement must not collide with another's cached narrative."""
    import app.services.draft_writer as _dw

    responses = iter(["narrative one", "narrative two"])
    monkeypatch.setattr(
        _dw, "get_llm", lambda tier="default": _FakeProvider(next(responses))
    )

    first = _dw._hyde_document("Technical Approach", "Requirement A.")
    second = _dw._hyde_document("Technical Approach", "Requirement B.")

    assert (first, second) == ("narrative one", "narrative two")


def test_retrieve_section_context_falls_back_to_raw_text_when_hyde_fails(monkeypatch):
    """HyDE generation is an extra LLM call and must never block retrieval — a
    failure there falls back to the plain section+requirement query."""
    import app.services.draft_writer as _dw

    class _ExplodingProvider:
        def generate_text(self, prompt, system=None):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(_dw, "get_llm", lambda tier="default": _ExplodingProvider())

    queries_seen: list[str] = []

    def fake_search(uploaded_by, query, top_k, min_score, **kwargs):
        queries_seen.append(query)
        return []

    monkeypatch.setattr(_dw, "search_similar", fake_search)

    context, grounded_count, weak = _dw._retrieve_section_context(
        uploaded_by="u",
        section_title="Technical Approach",
        requirement_texts=["The contractor SHALL deliver widgets."],
        top_k=5,
        use_hyde=True,
    )

    assert queries_seen[0] == "Technical Approach\nThe contractor SHALL deliver widgets."
    assert context == []


def test_diversify_caps_chunks_per_source(monkeypatch):
    """5 'matches' that are really 5 adjacent chunks of one past proposal must
    not fill the whole context — other sources get a fair shot at a slot."""
    import app.services.draft_writer as _dw

    hits = (
        [
            {"chunk_id": f"dom-{i}", "source_name": "dominant.pdf", "content": "c", "score": 0.9 - i * 0.01}
            for i in range(5)
        ]
        + [{"chunk_id": "other-1", "source_name": "other.pdf", "content": "c", "score": 0.5}]
    )

    selected = _dw._diversify(hits, top_k=3)

    assert len(selected) == 3
    counts: dict[str, int] = {}
    for h in selected:
        counts[h["source_name"]] = counts.get(h["source_name"], 0) + 1
    assert counts["dominant.pdf"] <= _dw._MAX_CHUNKS_PER_SOURCE
    assert "other.pdf" in counts  # the lone other source still got a slot


def test_diversify_backfills_from_overflow_when_one_source_dominates():
    """If the corpus genuinely only has one source, the diversity cap must not
    under-fill the context — better a repeated source than fewer chunks."""
    import app.services.draft_writer as _dw

    hits = [
        {"chunk_id": f"dom-{i}", "source_name": "only.pdf", "content": "c", "score": 0.9 - i * 0.01}
        for i in range(5)
    ]

    selected = _dw._diversify(hits, top_k=3)

    assert len(selected) == 3  # backfilled past the per-source cap to reach top_k


# ---------------------------------------------------------------------------
# generate_section_draft: retrieval + LLM stubbed, guardrail wiring is real
# ---------------------------------------------------------------------------

import uuid

from app.services import draft_writer as _dw
from app.services.guardrails import DraftGuardrailError


class _FakeProvider:
    """Stand-in for get_llm() — returns canned text instead of calling out."""

    def __init__(self, text: str):
        self._text = text

    def generate_text(self, prompt: str, system: str | None = None) -> str:
        return self._text


def test_generate_section_draft_enforces_the_heading_guardrail(monkeypatch):
    """The section writer's system prompt mandates fixed headings; a draft that
    dropped them entirely must be rejected, not silently persisted as prose."""
    monkeypatch.setattr(_dw, "search_similar", lambda *a, **kw: [])
    monkeypatch.setattr(
        _dw,
        "get_llm",
        lambda tier="default": _FakeProvider(
            "We will deliver the widgets on schedule under this contract, with "
            "no markdown structure of any kind anywhere in this response — just "
            "plain prose describing the approach the offeror intends to take."
        ),
    )

    with pytest.raises(DraftGuardrailError, match="heading"):
        _dw.generate_section_draft(
            uploaded_by=uuid.uuid4(),
            section_title="Technical Approach",
            requirement_texts=["The contractor SHALL deliver widgets."],
        )


def test_generate_section_draft_citations_carry_content_for_the_critic(monkeypatch):
    """Citations returned to the caller must include the retrieved chunk text,
    not just its score/source — the compliance critic verifies claims against
    this text, and a name+score pair alone gives it nothing to check against."""
    monkeypatch.setattr(
        _dw,
        "search_similar",
        lambda *a, **kw: [
            {
                "chunk_id": "c1",
                "source_name": "past.pdf",
                "content": "412 depot overhauls under W91QUZ-19-C-0042.",
                "score": 0.81,
            }
        ],
    )
    monkeypatch.setattr(
        _dw,
        "get_llm",
        lambda tier="default": _FakeProvider(
            "## Technical Approach\n\nWe will deliver the widgets on schedule, "
            "drawing on our prior depot overhaul work under W91QUZ-19-C-0042, "
            "which demonstrates the throughput this delivery schedule requires. "
            "[Req 1]"
        ),
    )

    result = _dw.generate_section_draft(
        uploaded_by=uuid.uuid4(),
        section_title="Technical Approach",
        requirement_texts=["The contractor SHALL deliver widgets."],
    )

    assert result["citations"] == [
        {
            "source_name": "past.pdf",
            "score": 0.81,
            "content": "412 depot overhauls under W91QUZ-19-C-0042.",
        }
    ]
