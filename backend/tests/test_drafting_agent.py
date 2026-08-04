"""Integration test for the proposal drafting agent (Sprint 3 — AI writer).

Exercises the real LangGraph flow against a live Postgres, isolating only the
two external LLM touchpoints:

    load_context → plan_outline (stubbed) → fan out per section:
        (draft_section (stubbed) → check_compliance (stubbed) → save_section) → END

Requirements to run (same as test_ingestion_pipeline.py):
  * a reachable Postgres with the init + rag schema applied
  * langgraph installed (in requirements.txt)

We stub the planner (`_call_planner`) and the section writer
(`generate_section_draft`) so the test is deterministic and needs no Gemini key
or vector store, while everything else — ref resolution, the draft→save loop,
and the DB writes to proposal_sections — runs for real.
"""

import json
import uuid

import psycopg2
import pytest

from app.agent import drafting_agent
from app.agent.drafting_agent import ComplianceReview, PlannedSection, ProposalOutline
from app.core.config import settings


def _passing_critic(*args, **kwargs):
    return ComplianceReview(addressed=True, evaluation_alignment=True, feedback="")


def _planned(title: str, refs: list[int], brief: str, **kwargs) -> PlannedSection:
    """PlannedSection with the required scalars filled in.

    `target_words` is required-with-no-default (a schema default breaks Gemini
    structured output), so tests would otherwise repeat it everywhere.
    """
    kwargs.setdefault("target_words", 0)
    return PlannedSection(
        section_title=title, requirement_refs=refs, brief=brief, **kwargs
    )


def _fake_draft(content: str = "Draft.", grounded: bool = True):
    """A `generate_section_draft` stub that records the kwargs it was handed.

    Returns (stub, calls) — `calls` collects every call's kwargs so tests can
    assert on the compliance frame the agent threaded through.
    """
    calls: list[dict] = []

    def stub(uploaded_by, section_title, requirement_texts, **kwargs):
        calls.append({"section_title": section_title, **kwargs})
        body = content.format(n=len(calls)) if "{n}" in content else content
        return {"content": body, "grounded": grounded, "citations": []}

    return stub, calls


@pytest.fixture
def seeded_rfp():
    """Seeds a user + rfp_document + proposal + two extracted requirements.

    The proposal is required, not incidental: drafting is addressed by proposal
    id because sections belong to the proposal rather than the document.
    """
    user_id = str(uuid.uuid4())
    rfp_id = str(uuid.uuid4())
    proposal_id = str(uuid.uuid4())
    req_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    email = f"draft_{uuid.uuid4().hex[:6]}@example.com"
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id, email, password_hash, first_name, last_name) "
        "VALUES (%s, %s, 'hash', 'Draft', 'Tester');",
        (user_id, email),
    )
    cur.execute(
        "INSERT INTO rfp_documents (rfp_id, uploaded_by, file_name, s3_storage_key, "
        "processing_status) VALUES (%s, %s, 'rfp.pdf', 'uploads/x', 'completed');",
        (rfp_id, user_id),
    )
    cur.execute(
        "INSERT INTO proposals (proposal_id, owned_by, rfp_id, title) "
        "VALUES (%s, %s, %s, 'Drafting Test Bid');",
        (proposal_id, user_id, rfp_id),
    )
    cur.executemany(
        "INSERT INTO extracted_requirements (requirement_id, rfp_id, section_number, "
        "raw_text_content, category) VALUES (%s, %s, %s, %s, %s);",
        [
            (req_ids[0], rfp_id, "C.3.1", "The contractor SHALL deliver widgets.", "Technical"),
            (req_ids[1], rfp_id, "H.2", "MFA is REQUIRED for privileged access.", "Security"),
        ],
    )
    conn.commit()
    yield {
        "user_id": user_id,
        "rfp_id": rfp_id,
        "proposal_id": proposal_id,
        "req_ids": req_ids,
    }
    cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))  # cascades
    conn.commit()
    cur.close()
    conn.close()


def _fetch_sections(proposal_id: str) -> list[dict]:
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT section_title, generated_draft_content, requirement_id, status, review_notes "
        "FROM proposal_sections WHERE proposal_id = %s ORDER BY section_title;",
        (proposal_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "title": r[0],
            "content": r[1],
            "requirement_id": str(r[2]) if r[2] else None,
            "status": r[3],
            "review_notes": r[4],
        }
        for r in rows
    ]


def test_draft_full_proposal_end_to_end(seeded_rfp, monkeypatch):
    rfp_id = seeded_rfp["rfp_id"]
    proposal_id = seeded_rfp["proposal_id"]
    req_ids = seeded_rfp["req_ids"]

    # Planner groups requirement ref 0 → Technical Approach, ref 1 → Security.
    def fake_planner(_prompt: str) -> ProposalOutline:
        return ProposalOutline(
            sections=[
                _planned("Technical Approach", [0], "tech"),
                _planned("Security Plan", [1], "sec"),
            ]
        )

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)

    # Section writer returns deterministic prose (no retrieval / Gemini).
    def fake_section_draft(uploaded_by, section_title, requirement_texts, **kwargs):
        return {"content": f"Draft for {section_title}.", "grounded": True, "citations": []}

    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    result = drafting_agent.run_drafting_sync(proposal_id)

    assert result["sections"] == 2
    assert len(result["section_ids"]) == 2

    sections = _fetch_sections(proposal_id)
    titles = [s["title"] for s in sections]
    assert titles == ["Security Plan", "Technical Approach"]  # ordered by title
    assert all(s["status"] == "needs_review" for s in sections)
    assert all(s["content"].startswith("Draft for ") for s in sections)

    # Each section is linked back to the requirement it answers.
    linked = {s["title"]: s["requirement_id"] for s in sections}
    assert linked["Technical Approach"] == req_ids[0]
    assert linked["Security Plan"] == req_ids[1]


def test_critic_drives_one_revision(seeded_rfp, monkeypatch):
    """The compliance critic rejects the first draft, then passes the revision."""
    rfp_id = seeded_rfp["rfp_id"]
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)

    # Fail the first review, pass the second → exactly one revision.
    reviews = iter(
        [
            ComplianceReview(
                addressed=False,
                evaluation_alignment=True,
                feedback="Cite a specific past contract.",
            ),
            ComplianceReview(addressed=True, evaluation_alignment=True, feedback=""),
        ]
    )
    monkeypatch.setattr(drafting_agent, "_call_critic", lambda *a, **kw: next(reviews))

    fake_section_draft, draft_calls = _fake_draft("Draft v{n}.")
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    result = drafting_agent.run_drafting_sync(proposal_id)

    # Two draft attempts (initial + one revision); the revision saw the feedback.
    assert len(draft_calls) == 2
    assert draft_calls[0]["feedback"] is None
    assert draft_calls[1]["feedback"] == "Cite a specific past contract."

    # One section persisted, holding the revised content.
    assert result["sections"] == 1
    sections = _fetch_sections(proposal_id)
    assert len(sections) == 1
    assert sections[0]["content"] == "Draft v2."
    assert sections[0]["status"] == "needs_review"


def test_draft_failure_is_isolated_to_section(seeded_rfp, monkeypatch):
    """A non-guardrail draft failure must not sink the run: the section is
    persisted empty/needs-attention and drafting continues (fix #1)."""
    rfp_id = seeded_rfp["rfp_id"]
    proposal_id = seeded_rfp["proposal_id"]
    req_ids = seeded_rfp["req_ids"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)  # never reached

    # The writer blows up with a non-guardrail error (e.g. retrieval / LLM timeout).
    def exploding_section_draft(uploaded_by, section_title, requirement_texts, **kwargs):
        raise RuntimeError("retrieval backend unavailable")

    monkeypatch.setattr(drafting_agent, "generate_section_draft", exploding_section_draft)

    result = drafting_agent.run_drafting_sync(proposal_id)

    # The run completes and the section is still saved — empty, flagged for a human.
    assert result["sections"] == 1
    sections = _fetch_sections(proposal_id)
    assert len(sections) == 1
    assert sections[0]["content"] == ""
    assert sections[0]["status"] == "empty"
    assert sections[0]["requirement_id"] == req_ids[0]


def test_exhausted_critic_persists_review_notes(seeded_rfp, monkeypatch):
    """When the revision budget is spent with the critic still flagging gaps, the
    section is saved needs_review with the critic's final feedback (fix #7)."""
    rfp_id = seeded_rfp["rfp_id"]
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    # Critic is never satisfied — always returns the same actionable gap.
    monkeypatch.setattr(
        drafting_agent,
        "_call_critic",
        lambda *a, **kw: ComplianceReview(
            addressed=False,
            evaluation_alignment=True,
            feedback="Cite a specific past contract.",
        ),
    )

    fake_section_draft, draft_calls = _fake_draft("Draft v{n}.")
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    result = drafting_agent.run_drafting_sync(proposal_id)

    # Exactly _MAX_ATTEMPTS drafts, then saved needs_review with the last feedback.
    assert len(draft_calls) == drafting_agent._MAX_ATTEMPTS
    assert result["sections"] == 1
    sections = _fetch_sections(proposal_id)
    assert sections[0]["status"] == "needs_review"
    assert sections[0]["review_notes"] == "Cite a specific past contract."


def test_critic_failure_saves_draft_unreviewed(seeded_rfp, monkeypatch):
    """A failing compliance critic must neither crash the run nor silently pass:
    the draft is saved once as needs_review, with no revision loop (fix #2)."""
    rfp_id = seeded_rfp["rfp_id"]
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)

    def exploding_critic(*args, **kwargs):
        raise RuntimeError("critic model unavailable")

    monkeypatch.setattr(drafting_agent, "_call_critic", exploding_critic)

    fake_section_draft, draft_calls = _fake_draft("Draft v1.")
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    result = drafting_agent.run_drafting_sync(proposal_id)

    # Exactly one draft attempt — a failed critic does not trigger a revision.
    assert len(draft_calls) == 1
    assert draft_calls[0]["feedback"] is None

    # The draft is persisted for a human to verify, not dropped.
    assert result["sections"] == 1
    sections = _fetch_sections(proposal_id)
    assert len(sections) == 1
    assert sections[0]["content"] == "Draft v1."
    assert sections[0]["status"] == "needs_review"


# ---------------------------------------------------------------------------
# Compliance frame: the facts and rules that stop drafts coming out generic
# ---------------------------------------------------------------------------

def _seed_profile(user_id: str) -> None:
    """Gives the tenant a company profile — the offeror's citable facts."""
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO company_profiles (user_id, legal_name, cage_code, uei_number, "
        "socio_economic_status, certifications, past_performance) "
        "VALUES (%s, 'Acme Federal LLC', '7X9Q2', 'ABC123DEF456', %s, %s, %s);",
        (
            user_id,
            json.dumps(["SDVOSB", "8(a)"]),
            json.dumps(["ISO 9001:2015"]),
            json.dumps(
                [
                    {
                        "id": "pp1",
                        "contract_number": "W91QUZ-19-C-0042",
                        "agency": "US Army",
                        "value": 4200000.0,
                        "scope": "Depot-level widget overhaul",
                        "period": "2019-2023",
                    }
                ]
            ),
        ),
    )
    conn.commit()
    cur.close()
    conn.close()


def _seed_summary(rfp_id: str, summary: dict) -> None:
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "UPDATE rfp_documents SET solicitation_summary = %s WHERE rfp_id = %s;",
        (json.dumps(summary), rfp_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def test_company_profile_reaches_writer_planner_and_critic(seeded_rfp, monkeypatch):
    """The offeror's own facts must reach every LLM call.

    Without them the writer has nothing concrete to cite and falls back on
    generic corporate claims, and the critic cannot tell an unsupported claim
    from a supported one.
    """
    rfp_id = seeded_rfp["rfp_id"]
    proposal_id = seeded_rfp["proposal_id"]
    _seed_profile(seeded_rfp["user_id"])

    planner_prompts: list[str] = []

    def fake_planner(prompt):
        planner_prompts.append(prompt)
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    critic_calls: list[dict] = []

    def fake_critic(*args, **kwargs):
        critic_calls.append(kwargs)
        return _passing_critic()

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", fake_critic)
    fake_section_draft, draft_calls = _fake_draft()
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    # The planner sees the profile so it can derive verifiable win themes.
    assert "Acme Federal LLC" in planner_prompts[0]
    assert "SDVOSB" in planner_prompts[0]

    # The writer sees CAGE/UEI, set-aside status and the real prior contract.
    company = draft_calls[0]["company_context"]
    assert "7X9Q2" in company                # CAGE
    assert "ABC123DEF456" in company         # UEI
    assert "SDVOSB" in company
    assert "ISO 9001:2015" in company
    assert "W91QUZ-19-C-0042" in company     # past performance contract number

    # The critic is handed the same facts, as its definition of "supportable".
    assert "7X9Q2" in critic_calls[0]["company_context"]


def test_section_l_volumes_drive_the_outline(seeded_rfp, monkeypatch):
    """When the RFP mandates a proposal structure, the planner must mirror it —
    a proposal organised differently from Section L is non-responsive."""
    rfp_id = seeded_rfp["rfp_id"]
    proposal_id = seeded_rfp["proposal_id"]
    _seed_summary(
        rfp_id,
        {
            "submission_requirements": {
                "required_volumes_or_sections": [
                    {
                        "name": "Volume I — Technical",
                        "description": "Technical approach and staffing.",
                        "source_quote": "L.3.1",
                    },
                    {
                        "name": "Volume II — Price",
                        "description": "Fully burdened pricing.",
                        "source_quote": "L.3.2",
                    },
                ],
                "page_limits": [
                    {"volume": "Volume I", "limit": "30 pages", "source_quote": "L.4"}
                ],
            },
            "instructions_to_offerors": [
                {
                    "instruction": "Times New Roman 12pt, single sided.",
                    "applies_to": "All",
                    "source_quote": "L.2",
                }
            ],
        },
    )

    planner_prompts: list[str] = []

    def fake_planner(prompt):
        planner_prompts.append(prompt)
        return ProposalOutline(sections=[_planned("Volume I — Technical", [0], "t")])

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)
    fake_section_draft, draft_calls = _fake_draft()
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    prompt = planner_prompts[0]
    assert "REQUIRED PROPOSAL STRUCTURE (Section L" in prompt
    assert "Volume I — Technical" in prompt
    assert "Volume II — Price" in prompt

    # Page limits and Section L instructions reach the writer as solicitation context.
    sol = draft_calls[0]["solicitation_context"]
    assert "30 pages" in sol
    assert "Times New Roman 12pt" in sol


def test_evaluation_criteria_from_both_extractors_reach_the_section(
    seeded_rfp, monkeypatch
):
    """Section M criteria come from the requirement rows *and* the solicitation
    summary, and are excluded from the requirements a section must answer."""
    rfp_id = seeded_rfp["rfp_id"]
    proposal_id = seeded_rfp["proposal_id"]
    # An extra requirement row categorised as Section M.
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO extracted_requirements (requirement_id, rfp_id, section_number, "
        "raw_text_content, category) VALUES (%s, %s, 'M.2', "
        "'Technical merit is more important than price.', 'Evaluation Criteria');",
        (str(uuid.uuid4()), rfp_id),
    )
    conn.commit()
    cur.close()
    conn.close()

    _seed_summary(
        rfp_id,
        {
            "evaluation_factors": [
                {
                    "factor": "Past Performance",
                    "description": "Relevance and quality of prior work.",
                    "importance": "equal to technical merit",
                    "source_quote": "M.3",
                }
            ]
        },
    )

    planner_prompts: list[str] = []

    def fake_planner(prompt):
        planner_prompts.append(prompt)
        # Claim both criteria (refs 0 and 1) for the single section.
        return ProposalOutline(
            sections=[_planned("Technical Approach", [0], "t", evaluation_criteria_refs=[0, 1])]
        )

    critic_calls: list[dict] = []

    def fake_critic(*args, **kwargs):
        critic_calls.append(kwargs)
        return _passing_critic()

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", fake_critic)
    fake_section_draft, draft_calls = _fake_draft()
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    prompt = planner_prompts[0]
    assert "EVALUATION CRITERIA (Section M)" in prompt
    # The Section M row is offered as a criterion, never as a requirement to answer.
    requirements_block = prompt.split("REQUIREMENTS:")[1]
    assert "Technical merit is more important than price." not in requirements_block

    criteria = draft_calls[0]["evaluation_criteria"]
    assert any("Technical merit is more important" in c for c in criteria)  # from rows
    assert any("Past Performance" in c for c in criteria)                   # from summary
    assert critic_calls[0]["evaluation_criteria"] == criteria


def test_filler_alone_drives_a_revision(seeded_rfp, monkeypatch):
    """A draft can satisfy every requirement and still be unusable. Filler and
    unsupported claims must each be enough to send it back."""
    rfp_id = seeded_rfp["rfp_id"]
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    reviews = iter(
        [
            ComplianceReview(
                addressed=True,          # compliant …
                evaluation_alignment=True,
                unsupported_claims=["ISO 27001 certified"],
                filler_found=["world-class delivery excellence"],
                feedback="",             # … but unevidenced and padded
            ),
            ComplianceReview(addressed=True, evaluation_alignment=True, feedback=""),
        ]
    )
    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", lambda *a, **kw: next(reviews))
    fake_section_draft, draft_calls = _fake_draft("Draft v{n}.")
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    assert len(draft_calls) == 2, "filler/unsupported findings must trigger a revision"
    revision_feedback = draft_calls[1]["feedback"]
    assert "ISO 27001 certified" in revision_feedback
    assert "world-class delivery excellence" in revision_feedback

    assert _fetch_sections(proposal_id)[0]["content"] == "Draft v2."


def test_misaligned_evaluation_drives_a_revision(seeded_rfp, monkeypatch):
    """A compliant draft that never engages the evaluation criteria is sent back."""
    rfp_id = seeded_rfp["rfp_id"]
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    reviews = iter(
        [
            ComplianceReview(addressed=True, evaluation_alignment=False, feedback=""),
            ComplianceReview(addressed=True, evaluation_alignment=True, feedback=""),
        ]
    )
    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", lambda *a, **kw: next(reviews))
    fake_section_draft, draft_calls = _fake_draft("Draft v{n}.")
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    assert len(draft_calls) == 2
    assert "evaluation criteria" in draft_calls[1]["feedback"]


def test_ungrounded_section_is_flagged_for_review(seeded_rfp, monkeypatch):
    """A section drafted with no past-performance context is unevidenced. That
    has to show on the section itself, not only in the run's logs."""
    rfp_id = seeded_rfp["rfp_id"]
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)
    fake_section_draft, _ = _fake_draft("Draft.", grounded=False)
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    notes = _fetch_sections(proposal_id)[0]["review_notes"]
    assert notes and "past-performance" in notes
