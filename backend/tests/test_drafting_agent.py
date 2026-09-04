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
    return ComplianceReview(benefit_mapped=True, addressed=True, evaluation_alignment=True, feedback="")


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
        "raw_text_content, category, extraction_order) VALUES (%s, %s, %s, %s, %s, %s);",
        [
            (req_ids[0], rfp_id, "C.3.1", "The contractor SHALL deliver widgets.", "Technical", 0),
            (req_ids[1], rfp_id, "H.2", "MFA is REQUIRED for privileged access.", "Security", 1),
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


def _fetch_section_titles_in_sort_order(proposal_id: str) -> list[str]:
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT section_title FROM proposal_sections "
        "WHERE proposal_id = %s ORDER BY sort_order, created_at;",
        (proposal_id,),
    )
    titles = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return titles


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


def _fetch_trajectories(proposal_id: str) -> list[dict]:
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT section_title, final_status, stalled, attempt_count, attempts "
        "FROM drafting_trajectories WHERE proposal_id = %s ORDER BY outline_index;",
        (proposal_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "section_title": r[0],
            "final_status": r[1],
            "stalled": r[2],
            "attempt_count": r[3],
            "attempts": r[4],
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


def test_trajectory_write_failure_does_not_fail_the_run(seeded_rfp, monkeypatch):
    """A trajectory-write failure must be fail-open: the run still completes and
    the section still saves, exactly as if trajectory recording didn't exist."""
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)
    fake_section_draft, _ = _fake_draft("Draft.")
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    def exploding_record(*args, **kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(
        drafting_agent.trajectory_service, "record_section_trajectory", exploding_record
    )

    result = drafting_agent.run_drafting_sync(proposal_id)

    assert result["sections"] == 1
    sections = _fetch_sections(proposal_id)
    assert sections[0]["content"] == "Draft."
    assert _fetch_trajectories(proposal_id) == []


def test_retrieval_filters_reach_every_sections_draft_call(seeded_rfp, monkeypatch):
    """The knowledge-base pre-filter passed to run_drafting_sync must reach
    generate_section_draft for every section — the end-to-end wiring that
    makes the retrieval pre-filter (previously reachable only by calling
    draft_writer directly) usable through the real drafting entry point."""
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt: str) -> ProposalOutline:
        return ProposalOutline(
            sections=[
                _planned("Technical Approach", [0], "tech"),
                _planned("Security Plan", [1], "sec"),
            ]
        )

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)
    stub, calls = _fake_draft()
    monkeypatch.setattr(drafting_agent, "generate_section_draft", stub)

    filters = {"outcome": "won", "industry": "Marine Engineering"}
    result = drafting_agent.run_drafting_sync(proposal_id, retrieval_filters=filters)

    assert result["sections"] == 2
    assert len(calls) == 2
    assert all(c["retrieval_filters"] == filters for c in calls)


def test_no_retrieval_filters_by_default(seeded_rfp, monkeypatch):
    """Omitting retrieval_filters (every caller today) must reach the writer as
    None — no filtering, unchanged from before this existed."""
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt: str) -> ProposalOutline:
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "tech")])

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)
    stub, calls = _fake_draft()
    monkeypatch.setattr(drafting_agent, "generate_section_draft", stub)

    drafting_agent.run_drafting_sync(proposal_id)

    assert len(calls) == 1
    assert calls[0]["retrieval_filters"] is None


def test_section_order_follows_the_outline_not_completion_time(seeded_rfp, monkeypatch):
    """Sections draft concurrently (run_drafting fans out with asyncio.gather),
    so whichever needs less work can finish — and insert into proposal_sections
    — before one that comes earlier in the outline. The persisted order must
    still reflect the outline's (Section-L-mirroring) sequence, not whichever
    finished first."""
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt: str) -> ProposalOutline:
        return ProposalOutline(
            sections=[
                _planned("Technical Approach", [0], "tech"),  # outline position 0
                _planned("Security Plan", [1], "sec"),  # outline position 1
            ]
        )

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)

    # "Technical Approach" (outline position 0) is made slower than "Security
    # Plan" (position 1), so Security Plan is the one expected to actually
    # finish, and insert its DB row, first.
    import time

    def fake_section_draft(uploaded_by, section_title, requirement_texts, **kwargs):
        if section_title == "Technical Approach":
            time.sleep(0.15)
        return {"content": f"Draft for {section_title}.", "grounded": True, "citations": []}

    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    assert _fetch_section_titles_in_sort_order(proposal_id) == [
        "Technical Approach",
        "Security Plan",
    ]


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
                benefit_mapped=True,
                addressed=False,
                evaluation_alignment=True,
                feedback="Cite a specific past contract.",
            ),
            ComplianceReview(benefit_mapped=True, addressed=True, evaluation_alignment=True, feedback=""),
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

    # Both revision rounds survive in the trajectory — unlike review_notes,
    # which only ever holds the latest round's feedback.
    trajectories = _fetch_trajectories(proposal_id)
    assert len(trajectories) == 1
    traj = trajectories[0]
    assert traj["final_status"] == "saved"
    assert traj["attempt_count"] == 2
    assert len(traj["attempts"]) == 2
    assert traj["attempts"][0]["critic"]["feedback"] == "Cite a specific past contract."
    assert traj["attempts"][0]["critic"]["addressed"] is False
    assert traj["attempts"][1]["critic"]["addressed"] is True


def test_revision_feedback_accumulates_across_multiple_rounds(seeded_rfp, monkeypatch):
    """Each revision must see the *whole* trail of critic feedback, not just the
    latest round. The writer regenerates each attempt from scratch (no
    incremental edit), so without the full trail a fix in round 2 can silently
    reintroduce something round 1's feedback already resolved."""
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    reviews = iter(
        [
            ComplianceReview(
                benefit_mapped=True,
                addressed=False, evaluation_alignment=True,
                feedback="Cite a specific past contract.",
            ),
            ComplianceReview(
                benefit_mapped=True,
                addressed=False, evaluation_alignment=True,
                feedback="Ground the staffing claim in the company profile.",
            ),
            ComplianceReview(benefit_mapped=True, addressed=True, evaluation_alignment=True, feedback=""),
        ]
    )
    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", lambda *a, **kw: next(reviews))

    fake_section_draft, draft_calls = _fake_draft("Draft v{n}.")
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    # Three attempts: initial + two critic-driven revisions.
    assert len(draft_calls) == 3
    assert draft_calls[0]["feedback"] is None
    # A single prior round is passed through unwrapped.
    assert draft_calls[1]["feedback"] == "Cite a specific past contract."
    # Two+ rounds are labeled and both are present — nothing is dropped.
    combined = draft_calls[2]["feedback"]
    assert "Cite a specific past contract." in combined
    assert "Ground the staffing claim in the company profile." in combined
    assert combined.index("Cite a specific past contract.") < combined.index(
        "Ground the staffing claim in the company profile."
    )


def test_critic_receives_the_writer_evidence_chunks(seeded_rfp, monkeypatch):
    """The critic must see the actual retrieved past-performance text the writer
    was given, not just the company profile summary — otherwise it can only
    judge plausibility, not verify a claim traces to a specific source."""
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    citations = [
        {
            "source_name": "past_bid.pdf",
            "score": 0.81,
            "content": "412 depot overhauls under W91QUZ-19-C-0042.",
        }
    ]

    def fake_section_draft(uploaded_by, section_title, requirement_texts, **kwargs):
        return {"content": "Draft.", "grounded": True, "citations": citations}

    critic_calls: list[dict] = []

    def fake_critic(*args, **kwargs):
        critic_calls.append(kwargs)
        return _passing_critic()

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", fake_critic)
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    assert critic_calls[0]["citations"] == citations


def test_unused_evidence_is_flagged_when_the_critic_reports_it(seeded_rfp, monkeypatch):
    """Retrieval can hand the writer evidence it never actually leans on. When
    the critic explicitly names which sources the draft *does* reflect, the
    gap between 'supplied' and 'actually cited' belongs in review_notes — a
    reviewer needs to know retrieval was broader than what the draft uses."""
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    citations = [
        {"source_name": "cited.pdf", "score": 0.8, "content": "c"},
        {"source_name": "extra.pdf", "score": 0.6, "content": "c"},
    ]

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(
        drafting_agent,
        "_call_critic",
        lambda *a, **kw: ComplianceReview(
            benefit_mapped=True,
            addressed=True, evaluation_alignment=True, feedback="",
            cited_sources=["cited.pdf"],
        ),
    )
    monkeypatch.setattr(
        drafting_agent,
        "generate_section_draft",
        lambda **kw: {"content": "Draft.", "grounded": True, "citations": citations},
    )

    drafting_agent.run_drafting_sync(proposal_id)

    notes = _fetch_sections(proposal_id)[0]["review_notes"]
    assert notes and "extra.pdf" in notes
    assert "cited.pdf" not in notes  # only the unused source is named


def test_no_unused_evidence_note_when_the_critic_stays_silent_on_it(seeded_rfp, monkeypatch):
    """An empty `cited_sources` is ambiguous — it could mean 'nothing was used'
    or just that this critic response predates the field. Treated as no signal,
    not as a claim that nothing was used, so no note is added and older/stubbed
    critics don't produce a spurious warning on every section."""
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)
    monkeypatch.setattr(
        drafting_agent,
        "generate_section_draft",
        lambda **kw: {
            "content": "Draft.",
            "grounded": True,
            "citations": [{"source_name": "past.pdf", "score": 0.8, "content": "c"}],
        },
    )

    drafting_agent.run_drafting_sync(proposal_id)

    notes = _fetch_sections(proposal_id)[0]["review_notes"]
    assert notes is None


def test_critic_loop_stops_early_when_findings_stop_changing(seeded_rfp, monkeypatch):
    """If the exact same unsupported-claim/filler finding survives a revision
    unchanged, the fix isn't converging — the writer regenerates each attempt
    from scratch, so a repeat means it's circling, not closing the gap. Better
    to stop and flag it for a human than spend the rest of the budget on
    identical attempts."""
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(
        drafting_agent,
        "_call_critic",
        lambda *a, **kw: ComplianceReview(
            benefit_mapped=True,
            addressed=False,
            evaluation_alignment=True,
            unsupported_claims=["ISO 27001 certified"],
            feedback="Ground this claim.",
        ),
    )
    fake_section_draft, draft_calls = _fake_draft("Draft v{n}.")
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    # Stops after 2 attempts, not the full _MAX_ATTEMPTS=3 budget, because the
    # same unsupported claim survived the revision unchanged.
    assert len(draft_calls) == 2
    sections = _fetch_sections(proposal_id)
    assert sections[0]["status"] == "needs_review"
    assert "repeated the same finding" in sections[0]["review_notes"]

    traj = _fetch_trajectories(proposal_id)[0]
    assert traj["stalled"] is True
    assert traj["attempt_count"] == 2


def test_critic_loop_does_not_stall_on_differing_findings(seeded_rfp, monkeypatch):
    """A revision that changes *what* the critic flags (not just re-flags the
    same thing) must still get its full attempt budget — the loop is making
    progress, it just hasn't finished."""
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    reviews = iter(
        [
            ComplianceReview(
                benefit_mapped=True,
                addressed=False, evaluation_alignment=True,
                unsupported_claims=["ISO 27001 certified"], feedback="Fix A.",
            ),
            ComplianceReview(
                benefit_mapped=True,
                addressed=False, evaluation_alignment=True,
                unsupported_claims=["CMMC Level 2"], feedback="Fix B.",
            ),
            ComplianceReview(benefit_mapped=True, addressed=True, evaluation_alignment=True, feedback=""),
        ]
    )
    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", lambda *a, **kw: next(reviews))
    fake_section_draft, draft_calls = _fake_draft("Draft v{n}.")
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    assert len(draft_calls) == 3  # full budget used — each round made distinct progress


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

    # A trajectory row still exists, recording the draft-time exception, even
    # though the section itself has no content to show for it.
    traj = _fetch_trajectories(proposal_id)[0]
    assert traj["final_status"] == "draft_failed"
    assert traj["attempts"][0]["draft_error"] is not None


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
            benefit_mapped=True,
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

    # The section still saves, and the trajectory records the critic failure
    # against that attempt rather than silently showing no review ever happened.
    assert result["sections"] == 1
    traj = _fetch_trajectories(proposal_id)[0]
    assert traj["attempt_count"] == 1
    assert "error" in traj["attempts"][0]["critic"]

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
                benefit_mapped=True,
                addressed=True,          # compliant …
                evaluation_alignment=True,
                unsupported_claims=["ISO 27001 certified"],
                filler_found=["world-class delivery excellence"],
                feedback="",             # … but unevidenced and padded
            ),
            ComplianceReview(benefit_mapped=True, addressed=True, evaluation_alignment=True, feedback=""),
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
            ComplianceReview(benefit_mapped=True, addressed=True, evaluation_alignment=False, feedback=""),
            ComplianceReview(benefit_mapped=True, addressed=True, evaluation_alignment=True, feedback=""),
        ]
    )
    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", lambda *a, **kw: next(reviews))
    fake_section_draft, draft_calls = _fake_draft("Draft v{n}.")
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    assert len(draft_calls) == 2
    assert "evaluation criteria" in draft_calls[1]["feedback"]


def test_unmapped_benefit_drives_a_revision(seeded_rfp, monkeypatch):
    """A draft can be compliant, evidenced, and on-topic and still just list
    features without ever saying why they matter to the government — that's a
    feature dump, not a scored argument, and must be sent back on its own,
    independent of every other dimension passing."""
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    reviews = iter(
        [
            ComplianceReview(
                benefit_mapped=False, addressed=True, evaluation_alignment=True, feedback="",
            ),
            ComplianceReview(
                benefit_mapped=True, addressed=True, evaluation_alignment=True, feedback="",
            ),
        ]
    )
    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", lambda *a, **kw: next(reviews))
    fake_section_draft, draft_calls = _fake_draft("Draft v{n}.")
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    assert len(draft_calls) == 2
    assert "operational benefit" in draft_calls[1]["feedback"]


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


def test_partially_grounded_section_is_flagged_for_review(seeded_rfp, monkeypatch):
    """A section can have *some* evidence and still be mostly unevidenced — 2 of
    5 requirements backed reads very differently from 5 of 5, and the reviewer
    must see which one this was, not just a blanket 'grounded' flag."""
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)
    monkeypatch.setattr(
        drafting_agent,
        "generate_section_draft",
        lambda **kw: {
            "content": "Drafted body.",
            "grounded": True,
            "grounded_requirement_count": 2,
            "requirement_count": 5,
            "weak_grounding": False,
            "citations": [{"source_name": "past.pdf", "score": 0.7, "content": "c"}],
        },
    )

    drafting_agent.run_drafting_sync(proposal_id)

    notes = _fetch_sections(proposal_id)[0]["review_notes"]
    assert notes and "2/5 requirement" in notes


def test_weakly_grounded_section_is_flagged_for_review(seeded_rfp, monkeypatch):
    """Evidence that only cleared the relaxed fallback floor is weaker than a
    clean match — the reviewer needs to know to double-check it, not see the
    same confident 'grounded' signal as a section backed by a strong match."""
    proposal_id = seeded_rfp["proposal_id"]

    def fake_planner(_prompt):
        return ProposalOutline(sections=[_planned("Technical Approach", [0], "t")])

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)
    monkeypatch.setattr(
        drafting_agent,
        "generate_section_draft",
        lambda **kw: {
            "content": "Drafted body.",
            "grounded": True,
            "grounded_requirement_count": 1,
            "requirement_count": 1,
            "weak_grounding": True,
            "citations": [{"source_name": "past.pdf", "score": 0.25, "content": "c"}],
        },
    )

    drafting_agent.run_drafting_sync(proposal_id)

    notes = _fetch_sections(proposal_id)[0]["review_notes"]
    assert notes and "relevance threshold" in notes


# ---------------------------------------------------------------------------
# Drafting lifecycle (migration 0005): the flag belongs to the proposal
# ---------------------------------------------------------------------------

def _fetch_drafting(proposal_id: str) -> tuple[str, str | None]:
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT drafting_status, drafting_failure_reason FROM proposals "
        "WHERE proposal_id = %s;",
        (proposal_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0], row[1]


def _fetch_doc_status(rfp_id: str) -> tuple[str, str | None]:
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT processing_status, failure_reason FROM rfp_documents WHERE rfp_id = %s;",
        (rfp_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0], row[1]


def _second_proposal_on(rfp_id: str, user_id: str) -> str:
    """A competing bid on the same solicitation — the case that motivated 0005."""
    proposal_id = str(uuid.uuid4())
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO proposals (proposal_id, owned_by, rfp_id, title) "
        "VALUES (%s, %s, %s, 'Second Bid');",
        (proposal_id, user_id, rfp_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return proposal_id


def test_drafting_status_is_recorded_on_the_proposal_not_the_document(
    seeded_rfp, monkeypatch
):
    """Drafting one bid must not report progress for another on the same RFP.

    The flag used to live on `rfp_documents.processing_status`, so the second
    proposal here would have read 'drafted' without a single section of its own
    ever being written, and the document would have been left carrying a
    drafting state that has nothing to do with ingestion.
    """
    rfp_id = seeded_rfp["rfp_id"]
    drafted = seeded_rfp["proposal_id"]
    untouched = _second_proposal_on(rfp_id, seeded_rfp["user_id"])

    monkeypatch.setattr(
        drafting_agent,
        "_call_planner",
        lambda _p: ProposalOutline(sections=[_planned("Technical Approach", [0], "t")]),
    )
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)
    fake_section_draft, _ = _fake_draft()
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(drafted)

    assert _fetch_drafting(drafted) == ("drafted", None)
    assert _fetch_drafting(untouched) == ("idle", None)
    # The document only ever describes how far ingestion got.
    assert _fetch_doc_status(rfp_id) == ("completed", None)


def test_failed_drafting_records_its_reason_on_the_proposal(seeded_rfp, monkeypatch):
    """A failed draft is attributable to the bid that failed, with a reason.

    Recording it on the document meant a second proposal on the same RFP showed
    a failure it never had — and the reason overwrote any genuine *ingestion*
    failure reason sitting in the same column.
    """
    rfp_id = seeded_rfp["rfp_id"]
    proposal_id = seeded_rfp["proposal_id"]
    other = _second_proposal_on(rfp_id, seeded_rfp["user_id"])

    def exploding_planner(_prompt):
        raise RuntimeError("model gemini-1.0-pro is not found")

    monkeypatch.setattr(drafting_agent, "_call_planner", exploding_planner)

    with pytest.raises(RuntimeError):
        drafting_agent.run_drafting_sync(proposal_id)

    status, reason = _fetch_drafting(proposal_id)
    assert status == "draft_failed"
    assert reason and "is not found" in reason  # the actionable part, not a traceback

    assert _fetch_drafting(other) == ("idle", None)
    assert _fetch_doc_status(rfp_id) == ("completed", None)


def test_a_successful_rerun_clears_the_previous_failure_reason(seeded_rfp, monkeypatch):
    """Otherwise a proposal that now drafts fine still displays the old error."""
    proposal_id = seeded_rfp["proposal_id"]

    monkeypatch.setattr(
        drafting_agent,
        "_call_planner",
        lambda _p: (_ for _ in ()).throw(RuntimeError("transient provider outage")),
    )
    with pytest.raises(RuntimeError):
        drafting_agent.run_drafting_sync(proposal_id)
    assert _fetch_drafting(proposal_id)[0] == "draft_failed"

    monkeypatch.setattr(
        drafting_agent,
        "_call_planner",
        lambda _p: ProposalOutline(sections=[_planned("Technical Approach", [0], "t")]),
    )
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)
    fake_section_draft, _ = _fake_draft()
    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    assert _fetch_drafting(proposal_id) == ("drafted", None)


def test_drafted_section_persists_its_retrieval_grounding(seeded_rfp, monkeypatch):
    """Confidence and citations reach the section the workspace renders.

    Both were hardcoded 0.0 and [] at the point of save, so a real RAG draft
    showed an empty confidence meter and no sources however well-evidenced it
    was — the retriever had computed both and the save path dropped them.
    """
    proposal_id = seeded_rfp["proposal_id"]

    monkeypatch.setattr(
        drafting_agent,
        "_call_planner",
        lambda _p: ProposalOutline(sections=[_planned("Technical Approach", [0], "t")]),
    )
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)

    def grounded_draft(**kwargs):
        return {
            "content": "Drafted body grounded in prior work.",
            "grounded": True,
            "citations": [
                {"source_name": "past_bid.pdf", "score": 0.82},
                {"source_name": "capability.docx", "score": 0.58},
                {"source_name": "past_bid.pdf", "score": 0.40},
            ],
        }

    monkeypatch.setattr(drafting_agent, "generate_section_draft", grounded_draft)

    drafting_agent.run_drafting_sync(proposal_id)

    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT ai_confidence_score, reference_tags FROM proposal_sections "
        "WHERE proposal_id = %s;",
        (proposal_id,),
    )
    score, tags = cur.fetchone()
    cur.close()
    conn.close()

    assert score == pytest.approx((0.82 + 0.58 + 0.40) / 3, abs=1e-4)
    assert tags == ["past_bid.pdf", "capability.docx"]  # deduped, strongest first


def test_ungrounded_section_persists_a_zero_score_and_no_sources(seeded_rfp, monkeypatch):
    """0.0 here is a finding, not a missing value — nothing supports the prose."""
    proposal_id = seeded_rfp["proposal_id"]

    monkeypatch.setattr(
        drafting_agent,
        "_call_planner",
        lambda _p: ProposalOutline(sections=[_planned("Technical Approach", [0], "t")]),
    )
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)
    monkeypatch.setattr(
        drafting_agent,
        "generate_section_draft",
        lambda **kw: {"content": "Generic body.", "grounded": False, "citations": []},
    )

    drafting_agent.run_drafting_sync(proposal_id)

    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT ai_confidence_score, reference_tags FROM proposal_sections "
        "WHERE proposal_id = %s;",
        (proposal_id,),
    )
    score, tags = cur.fetchone()
    cur.close()
    conn.close()

    assert score == 0.0
    assert tags == []
