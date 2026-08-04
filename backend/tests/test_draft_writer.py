"""Unit tests for the section draft writer's prompt assembly and profile block.

Pure unit tests: no DB, no vector store, no LLM. They pin down the contract the
drafting agent depends on — that every fact it threads through actually reaches
the model — because a silently dropped block produces plausible-looking but
generic prose rather than an error.
"""

from app.models.contract import CompanyProfile, PastPerformance
from app.services.draft_writer import (
    _SECTION_SYSTEM_PROMPT,
    _assemble_section_prompt,
    _format_company_profile,
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
