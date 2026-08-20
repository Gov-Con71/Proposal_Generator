"""Historical past-performance ingestion into pgvector (Story 3.1).

Shreds company past-performance text into chunks, embeds each with
google-genai, and stores them tenant-scoped in `historical_chunks`.
"""

import logging
from typing import Optional
from uuid import UUID

from pgvector.psycopg2 import register_vector

from app.core.db import get_connection
from app.services.embeddings import embed_texts
from app.services.semantic_chunker import semantic_chunks

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1200      # characters
_CHUNK_OVERLAP = 150


def chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Splits text into chunks for embedding, respecting heading/paragraph
    boundaries (`semantic_chunker.semantic_chunks`) rather than cutting at an
    arbitrary character count — a fixed sliding window used to risk severing a
    heading (e.g. "PROJECT SUMMARY") from the paragraph it introduces.

    `overlap` still applies, but only where `semantic_chunks` has no natural
    break point at all (a single paragraph longer than `size`) and must hard-
    cut mid-content — see its docstring. A retrieval/embedding index benefits
    from that overlap in exactly that case, so a fact split by the cut still
    has a chance of being embedded together somewhere.
    """
    return semantic_chunks(text, target_chars=size, max_chars=size, overlap_chars=overlap)


def store_history(
    uploaded_by: UUID,
    source_name: str,
    text: str,
    proposal_id: Optional[UUID] = None,
    *,
    industry: str | None = None,
    document_type: str | None = None,
    outcome: str | None = None,
) -> int:
    """Chunks, embeds, and stores past-performance text. Returns chunks written.

    `proposal_id` picks the pool: None writes to the tenant's long-term library
    (reusable across bids), a value attaches the document to that one proposal
    as supporting evidence, and it is removed with the proposal.

    `industry`, `document_type` (e.g. "past_performance", "case_study",
    "resume", "capability_statement"), and `outcome` (e.g. "won", "lost") are
    free-text tags applied to every chunk from this call, so `retrieval.
    search_similar` can pre-filter a search to a subset of the tenant's
    knowledge base before running the similarity match. All optional and
    unvalidated against a fixed vocabulary — same convention as
    `extracted_requirements.category` — so a tenant not using them sees no
    change, and the accepted-values list can grow without a migration.
    """
    chunks = chunk_text(text)
    if not chunks:
        return 0
    vectors = embed_texts(chunks)

    conn = get_connection()
    try:
        register_vector(conn)
        with conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO historical_chunks
                    (uploaded_by, source_name, content, embedding, proposal_id, industry, document_type, outcome)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                [
                    (
                        str(uploaded_by),
                        source_name,
                        chunk,
                        vector,
                        str(proposal_id) if proposal_id else None,
                        industry,
                        document_type,
                        outcome,
                    )
                    for chunk, vector in zip(chunks, vectors)
                ],
            )
    finally:
        conn.close()
    logger.info(
        "store_history: stored %d chunks for '%s' (%s; industry=%r, document_type=%r, outcome=%r)",
        len(chunks),
        source_name,
        f"proposal {proposal_id}" if proposal_id else "library",
        industry,
        document_type,
        outcome,
    )
    return len(chunks)


def delete_source(uploaded_by: UUID, source_name: str, proposal_id: Optional[UUID] = None) -> int:
    """Removes every chunk of one source from one pool. Returns rows deleted.

    Scoped by tenant *and* pool, so deleting a bid's copy of a document never
    touches the library copy of the same name.
    """
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM historical_chunks "
                "WHERE uploaded_by = %s AND source_name = %s "
                "AND proposal_id IS NOT DISTINCT FROM %s;",
                (
                    str(uploaded_by),
                    source_name,
                    str(proposal_id) if proposal_id else None,
                ),
            )
            deleted = cur.rowcount
    finally:
        conn.close()
    logger.info("delete_source: removed %d chunk(s) of '%s'", deleted, source_name)
    return deleted


def list_sources(uploaded_by: UUID, proposal_id: Optional[UUID] = None) -> list[dict]:
    """Returns each distinct source with its chunk count and tags, for ONE pool.

    None lists the long-term library; a proposal id lists only that bid's
    supporting documents. The pools are listed separately rather than merged
    because the two pages that show them mean different things by "my documents".
    Tags are read via MAX(): all chunks from one `store_history` call share
    the same tags by construction, so this is just picking the (single)
    value out of the group, not an aggregation across genuinely different tags.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_name, COUNT(*), MAX(created_at),
                       MAX(industry), MAX(document_type), MAX(outcome)
                FROM historical_chunks
                WHERE uploaded_by = %s
                  AND proposal_id IS NOT DISTINCT FROM %s
                GROUP BY source_name
                ORDER BY MAX(created_at) DESC;
                """,
                (str(uploaded_by), str(proposal_id) if proposal_id else None),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "source_name": r[0],
            "chunks": r[1],
            "created_at": r[2].isoformat() if r[2] else "",
            "industry": r[3],
            "document_type": r[4],
            "outcome": r[5],
        }
        for r in rows
    ]
