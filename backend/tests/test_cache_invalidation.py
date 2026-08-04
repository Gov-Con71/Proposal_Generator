"""Cache-invalidation guard.

The read cache is fail-open by design: a Redis outage degrades to a miss rather
than an error. That property is what makes a *missed eviction* so dangerous —
there is no failure to observe. GAP_ANALYSIS §1.3 is the precedent: the
ingestion worker wrote requirements straight to the database and never evicted
what the API had cached on the tenant's behalf, so the workspace served a stale
empty list with a 200 for the whole TTL and nothing anywhere reported a problem.

The invariant these tests exist to hold:

    Every writer of a cached entity must evict every key derived from it —
    including writers with no request context, i.e. the Celery workers.

Cached entities, and who writes them:

  requirements  reqs:{user}:{rfp}          ingestion worker; requirement PATCH/DELETE
  compliance    compliance:{user}:{rfp}    (derived from requirements — same writers)
  sections      secs:{user}:{proposal}     drafting agent; section create/update/
                                           approve/regenerate/generate

`render_export` writes only `export_jobs`, which nothing caches.

The fake below replaces the Redis client with a dict so the invariant is
exercised on its merits, rather than passing because caching happened to be
disabled or Redis happened to be unreachable in the test environment.
"""

import uuid
from pathlib import Path

import psycopg2
import pytest

from app.core import cache
from app.core.config import settings
from app.core.security import create_access_token


class FakeRedis:
    """Just enough Redis for the cache module, with no network and no TTL."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value if isinstance(value, bytes) else value.encode()

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)


@pytest.fixture
def fake_cache(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(cache, "_client", fake)
    monkeypatch.setattr(cache, "_redis", lambda: fake)
    monkeypatch.setattr(settings, "cache_enabled", True)
    yield fake
    monkeypatch.setattr(cache, "_client", None)


def _conn():
    return psycopg2.connect(settings.database_url)


@pytest.fixture
def tenant():
    """A user, an ingested RFP with one requirement, and two proposals on it."""
    user_id = str(uuid.uuid4())
    rfp_id = str(uuid.uuid4())
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, email, password_hash, first_name, last_name) "
            "VALUES (%s, %s, 'hash', 'Cache', 'Tester');",
            (user_id, f"cache_{uuid.uuid4().hex[:6]}@example.com"),
        )
        cur.execute(
            "INSERT INTO rfp_documents (rfp_id, uploaded_by, file_name, s3_storage_key, "
            "processing_status) VALUES (%s, %s, 'rfp.pdf', 'uploads/x', 'completed');",
            (rfp_id, user_id),
        )
        for pid, title in ((first, "First Bid"), (second, "Second Bid")):
            cur.execute(
                "INSERT INTO proposals (proposal_id, owned_by, rfp_id, title) "
                "VALUES (%s, %s, %s, %s);",
                (pid, user_id, rfp_id, title),
            )
        cur.execute(
            "INSERT INTO extracted_requirements (requirement_id, rfp_id, section_number, "
            "raw_text_content, category) VALUES (%s, %s, 'C.1', 'SHALL deliver.', 'Technical');",
            (str(uuid.uuid4()), rfp_id),
        )
    conn.close()
    yield {"user_id": user_id, "rfp_id": rfp_id, "first": first, "second": second}
    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))  # cascades
    conn.close()


def _auth(user_id: str) -> dict:
    token, _ = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def test_drafting_evicts_the_sections_it_writes(fake_cache, tenant, monkeypatch, test_client):
    """The workspace polls sections while drafting runs.

    So an empty list is cached long before the first section is saved, and the
    agent writes straight to the database — bypassing every eviction the API
    layer performs. Without the agent's own eviction the user watches drafting
    report success against a workspace that stays empty until the TTL expires.
    """
    from app.agent import drafting_agent
    from app.agent.drafting_agent import ProposalOutline, PlannedSection

    user_id, proposal_id = tenant["user_id"], tenant["first"]
    auth = _auth(user_id)

    # The poll that populates the cache with the pre-drafting (empty) answer.
    assert test_client.get(f"/proposals/{proposal_id}/sections", headers=auth).json() == []
    key = cache.sections_key(user_id, proposal_id)
    assert key in fake_cache.store, "precondition: the empty list really was cached"

    monkeypatch.setattr(
        drafting_agent,
        "_call_planner",
        lambda _p: ProposalOutline(
            sections=[
                PlannedSection(
                    section_title="Technical Approach",
                    requirement_refs=[0],
                    evaluation_criteria_refs=[],
                    win_themes=[],
                    brief="t",
                    target_words=0,
                )
            ]
        ),
    )
    monkeypatch.setattr(drafting_agent, "_call_critic", lambda *a, **kw: None)
    monkeypatch.setattr(
        drafting_agent,
        "generate_section_draft",
        lambda **kw: {"content": "Drafted body.", "grounded": True, "citations": []},
    )

    drafting_agent.run_drafting_sync(proposal_id)

    assert key not in fake_cache.store, "drafting must evict the sections it wrote"
    assert test_client.get(f"/proposals/{proposal_id}/sections", headers=auth).json() != []


def test_ingestion_evicts_every_proposal_built_on_the_document(
    fake_cache, tenant, monkeypatch
):
    """Requirements are per-document but sections are per-proposal.

    Re-ingesting replaces the compliance matrix, which clears section→requirement
    links (ON DELETE SET NULL), so *every* proposal on that RFP holds a stale
    sections entry. Evicting a single rfp-keyed entry — as the code did when
    sections were document-scoped — would now miss all of them.
    """
    from app.services import ingestion

    user_id, rfp_id = tenant["user_id"], tenant["rfp_id"]
    keys = [
        cache.requirements_key(user_id, rfp_id),
        cache.compliance_key(user_id, rfp_id),
        cache.sections_key(user_id, tenant["first"]),
        cache.sections_key(user_id, tenant["second"]),
    ]
    for k in keys:
        cache.cache_set(k, ["stale"])

    # Isolate S3 and both LLM reads; this test is about eviction, not extraction.
    from app.services.compliance_extractor import ComplianceMatrix, ExtractedRequirement

    class _NoopS3:
        def download_to_path(self, key, path):
            Path(path).write_text("The contractor SHALL deliver widgets.")

    async def _fake_parse(_path):
        return "The contractor SHALL deliver widgets."

    async def _fake_extract(_markdown):
        return ComplianceMatrix(
            requirements=[
                ExtractedRequirement(
                    section_number="C.1",
                    raw_text_content="The contractor SHALL deliver widgets.",
                    category="Technical",
                )
            ]
        )

    async def _no_summary(_markdown):
        return None

    monkeypatch.setattr(ingestion, "S3Storage", _NoopS3)
    monkeypatch.setattr(ingestion, "parse_to_markdown", _fake_parse)
    monkeypatch.setattr(ingestion, "run_extraction", _fake_extract)
    monkeypatch.setattr(ingestion, "run_solicitation_extraction", _no_summary)

    ingestion.run_ingestion_sync(rfp_id)

    assert [k for k in keys if k in fake_cache.store] == [], (
        "ingestion must evict the requirements, the compliance matrix, and the "
        "sections of every proposal on this document"
    )
