"""Historical past-performance ingestion into pgvector (Story 3.1).

Shreds company past-performance text into overlapping chunks, embeds each with
google-genai, and stores them tenant-scoped in `historical_chunks`.
"""

import logging
from typing import Optional
from uuid import UUID

from pgvector.psycopg2 import register_vector

from app.core.db import get_connection
from app.services.embeddings import embed_texts

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1200      # characters
_CHUNK_OVERLAP = 150


def chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Splits text into overlapping character windows on whitespace boundaries."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        # Prefer to break on whitespace so we don't cut words in half.
        if end < len(text):
            ws = text.rfind(" ", start + overlap, end)
            if ws != -1:
                end = ws
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def store_history(
    uploaded_by: UUID,
    source_name: str,
    text: str,
    proposal_id: Optional[UUID] = None,
) -> int:
    """Chunks, embeds, and stores past-performance text. Returns chunks written.

    `proposal_id` picks the pool: None writes to the tenant's long-term library
    (reusable across bids), a value attaches the document to that one proposal
    as supporting evidence, and it is removed with the proposal.
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
                    (uploaded_by, source_name, content, embedding, proposal_id)
                VALUES (%s, %s, %s, %s, %s);
                """,
                [
                    (
                        str(uploaded_by),
                        source_name,
                        chunk,
                        vector,
                        str(proposal_id) if proposal_id else None,
                    )
                    for chunk, vector in zip(chunks, vectors)
                ],
            )
    finally:
        conn.close()
    logger.info(
        "store_history: stored %d chunks for '%s' (%s)",
        len(chunks),
        source_name,
        f"proposal {proposal_id}" if proposal_id else "library",
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
    """Returns each distinct source with its chunk count, for ONE pool.

    None lists the long-term library; a proposal id lists only that bid's
    supporting documents. The pools are listed separately rather than merged
    because the two pages that show them mean different things by "my documents".
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_name, COUNT(*), MAX(created_at)
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
        {"source_name": r[0], "chunks": r[1], "created_at": r[2].isoformat() if r[2] else ""}
        for r in rows
    ]
