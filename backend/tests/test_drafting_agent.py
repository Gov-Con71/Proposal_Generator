"""Integration test for the proposal drafting agent (Sprint 3 — AI writer).

Exercises the real LangGraph flow against a live Postgres, isolating only the
two external LLM touchpoints:

    load_requirements → plan_outline (stubbed) → (draft_section (stubbed) → save_section)* → END

Requirements to run (same as test_ingestion_pipeline.py):
  * a reachable Postgres with the init + rag schema applied
  * langgraph installed (in requirements.txt)

We stub the planner (`_call_planner`) and the section writer
(`generate_section_draft`) so the test is deterministic and needs no Gemini key
or vector store, while everything else — ref resolution, the draft→save loop,
and the DB writes to proposal_sections — runs for real.
"""

import uuid

import psycopg2
import pytest

from app.agent import drafting_agent
from app.agent.drafting_agent import ComplianceReview, PlannedSection, ProposalOutline
from app.core.config import settings


def _passing_critic(section_title, requirement_texts, draft):
    return ComplianceReview(addressed=True, feedback="")


@pytest.fixture
def seeded_rfp():
    """Seeds a user + rfp_document + two extracted requirements; cleans up after."""
    user_id = str(uuid.uuid4())
    rfp_id = str(uuid.uuid4())
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
    cur.executemany(
        "INSERT INTO extracted_requirements (requirement_id, rfp_id, section_number, "
        "raw_text_content, category) VALUES (%s, %s, %s, %s, %s);",
        [
            (req_ids[0], rfp_id, "C.3.1", "The contractor SHALL deliver widgets.", "Technical"),
            (req_ids[1], rfp_id, "H.2", "MFA is REQUIRED for privileged access.", "Security"),
        ],
    )
    conn.commit()
    yield {"user_id": user_id, "rfp_id": rfp_id, "req_ids": req_ids}
    cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))  # cascades
    conn.commit()
    cur.close()
    conn.close()


def _fetch_sections(rfp_id: str) -> list[dict]:
    conn = psycopg2.connect(settings.database_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT section_title, generated_draft_content, requirement_id, status "
        "FROM proposal_sections WHERE rfp_id = %s ORDER BY section_title;",
        (rfp_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"title": r[0], "content": r[1], "requirement_id": str(r[2]) if r[2] else None, "status": r[3]}
        for r in rows
    ]


def test_draft_full_proposal_end_to_end(seeded_rfp, monkeypatch):
    rfp_id = seeded_rfp["rfp_id"]
    req_ids = seeded_rfp["req_ids"]

    # Planner groups requirement ref 0 → Technical Approach, ref 1 → Security.
    def fake_planner(_listing: str) -> ProposalOutline:
        return ProposalOutline(
            sections=[
                PlannedSection(section_title="Technical Approach", requirement_refs=[0], brief="tech"),
                PlannedSection(section_title="Security Plan", requirement_refs=[1], brief="sec"),
            ]
        )

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)
    monkeypatch.setattr(drafting_agent, "_call_critic", _passing_critic)

    # Section writer returns deterministic prose (no retrieval / Gemini).
    def fake_section_draft(uploaded_by, section_title, requirement_texts, top_k=5, feedback=None):
        return {"content": f"Draft for {section_title}.", "citations": []}

    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    result = drafting_agent.run_drafting_sync(rfp_id)

    assert result["sections"] == 2
    assert len(result["section_ids"]) == 2

    sections = _fetch_sections(rfp_id)
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

    def fake_planner(_listing):
        return ProposalOutline(
            sections=[PlannedSection(section_title="Technical Approach", requirement_refs=[0], brief="t")]
        )

    monkeypatch.setattr(drafting_agent, "_call_planner", fake_planner)

    # Fail the first review, pass the second → exactly one revision.
    reviews = iter(
        [
            ComplianceReview(addressed=False, feedback="Cite a specific past contract."),
            ComplianceReview(addressed=True, feedback=""),
        ]
    )
    monkeypatch.setattr(drafting_agent, "_call_critic", lambda *a: next(reviews))

    draft_calls: list[str | None] = []

    def fake_section_draft(uploaded_by, section_title, requirement_texts, top_k=5, feedback=None):
        draft_calls.append(feedback)
        return {"content": f"Draft v{len(draft_calls)}.", "citations": []}

    monkeypatch.setattr(drafting_agent, "generate_section_draft", fake_section_draft)

    result = drafting_agent.run_drafting_sync(rfp_id)

    # Two draft attempts (initial + one revision); the revision saw the feedback.
    assert len(draft_calls) == 2
    assert draft_calls[0] is None
    assert draft_calls[1] == "Cite a specific past contract."

    # One section persisted, holding the revised content.
    assert result["sections"] == 1
    sections = _fetch_sections(rfp_id)
    assert len(sections) == 1
    assert sections[0]["content"] == "Draft v2."
    assert sections[0]["status"] == "needs_review"
