"""Past-performance evidence pools (Sprint 9).

`historical_chunks` holds two kinds of evidence distinguished only by
`proposal_id`: the tenant's long-term library (NULL) and one bid's supporting
documents (set). The rules that matter, and what breaks if each is lost:

  * The pools must not leak. A bid's documents showing up in the library — or in
    another bid — is a tenancy-shaped bug inside a single tenant.
  * A bid's own documents must outrank the library. A user attaches documents
    *because* they are the relevant ones; making them compete on raw similarity
    against a large archive defeats the point of attaching them.
  * The library must still be reachable. Preference is not exclusivity — a thin
    upload must not starve sections the library could have grounded.
  * Deleting a proposal must take its documents with it. That cascade IS the
    lifecycle; without it "short-term" evidence accumulates forever.

Requires a reachable Postgres with the schema applied (as CI provides).
"""

import uuid

import psycopg2
import pytest

from app.core.config import settings
from app.services import history_service as history


def _conn():
    return psycopg2.connect(settings.database_url)


@pytest.fixture
def tenant():
    """A user plus one proposal of theirs. Both removed afterwards."""
    user_id = str(uuid.uuid4())
    proposal_id = str(uuid.uuid4())
    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (user_id, email, password_hash, first_name, last_name) "
            "VALUES (%s, %s, 'h', 'Pool', 'Tester');",
            (user_id, f"pool_{uuid.uuid4().hex[:6]}@example.com"),
        )
        cur.execute(
            "INSERT INTO proposals (proposal_id, owned_by, title) VALUES (%s, %s, 'Pool Test');",
            (proposal_id, user_id),
        )
    yield uuid.UUID(user_id), uuid.UUID(proposal_id)
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE user_id = %s;", (user_id,))
    conn.close()


def _chunk_count(user_id, proposal_id) -> int:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM historical_chunks "
                "WHERE uploaded_by = %s AND proposal_id IS NOT DISTINCT FROM %s;",
                (str(user_id), str(proposal_id) if proposal_id else None),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


def test_pools_are_listed_separately(tenant):
    user_id, proposal_id = tenant
    history.store_history(user_id, "library-doc", "Enterprise network modernization work.")
    history.store_history(user_id, "bid-doc", "Logistics ingestion pipeline work.", proposal_id)

    library = [s["source_name"] for s in history.list_sources(user_id)]
    bid = [s["source_name"] for s in history.list_sources(user_id, proposal_id)]

    assert library == ["library-doc"], "a bid's document leaked into the library listing"
    assert bid == ["bid-doc"], "a library document leaked into the bid listing"


def test_a_bids_documents_are_invisible_to_another_bid(tenant):
    """Two bids under one tenant must not see each other's supporting documents."""
    user_id, proposal_id = tenant
    other = uuid.uuid4()
    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO proposals (proposal_id, owned_by, title) VALUES (%s, %s, 'Other');",
            (str(other), str(user_id)),
        )
    conn.close()

    history.store_history(user_id, "bid-doc", "Only for the first bid.", proposal_id)

    assert history.list_sources(user_id, other) == []


def test_deleting_the_proposal_removes_its_documents_only(tenant):
    """The cascade is the whole lifecycle for short-term evidence."""
    user_id, proposal_id = tenant
    history.store_history(user_id, "library-doc", "Kept across every bid.")
    history.store_history(user_id, "bid-doc", "Attached to one bid.", proposal_id)
    assert _chunk_count(user_id, proposal_id) > 0

    conn = _conn()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM proposals WHERE proposal_id = %s;", (str(proposal_id),))
    conn.close()

    assert _chunk_count(user_id, proposal_id) == 0, "the bid's documents outlived the proposal"
    assert _chunk_count(user_id, None) > 0, "the cascade took the library with it"


def test_deleting_a_source_is_scoped_to_its_pool(tenant):
    """The same filename in both pools is two documents, not one."""
    user_id, proposal_id = tenant
    history.store_history(user_id, "shared-name", "The library copy.")
    history.store_history(user_id, "shared-name", "The bid copy.", proposal_id)

    history.delete_source(user_id, "shared-name", proposal_id)

    assert history.list_sources(user_id, proposal_id) == []
    assert [s["source_name"] for s in history.list_sources(user_id)] == ["shared-name"]
