"""Vector query + context ranking (Story 3.2).

Embeds a requirement/query and finds the closest historical chunks for the
tenant via pgvector cosine distance, returning ranked context blocks for the
draft writer.
"""

import logging
from uuid import UUID

from app.core.db import get_connection
from app.services.embeddings import embed_query

logger = logging.getLogger(__name__)


def _vector_literal(vec: list[float]) -> str:
    """Formats an embedding as pgvector's text literal (e.g. '[0.1,0.2]').

    The `<=>` operator has no `vector <=> numeric[]` form, so a bare Python list
    (sent as numeric[]) fails to match. Passing the canonical literal with an
    explicit `::vector` cast works regardless of array-cast availability.
    """
    return "[" + ",".join(map(str, vec)) + "]"


def tenant_history_count(uploaded_by: UUID) -> int:
    """Number of past-performance chunks the tenant has. Zero means drafts for
    this tenant cannot be grounded in retrieval (they will be generic)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM historical_chunks "
                "WHERE uploaded_by = %s AND embedding IS NOT NULL;",
                (str(uploaded_by),),
            )
            (count,) = cur.fetchone()
    finally:
        conn.close()
    return count


def search_similar(uploaded_by: UUID, query: str, top_k: int = 5) -> list[dict]:
    """Returns the top_k most similar historical chunks for the tenant.

    `score` is cosine similarity in [0, 1] (1 = identical direction).
    """
    if not query.strip():
        return []
    query_vec = _vector_literal(embed_query(query))

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # <=> is cosine distance (0 = identical); similarity = 1 - distance.
            cur.execute(
                """
                SELECT chunk_id, source_name, content,
                       1 - (embedding <=> %s::vector) AS score
                FROM historical_chunks
                WHERE uploaded_by = %s AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
                """,
                (query_vec, str(uploaded_by), query_vec, top_k),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    logger.info("search_similar: %d hits for query (%.40s...)", len(rows), query)
    return [
        {
            "chunk_id": str(r[0]),
            "source_name": r[1],
            "content": r[2],
            "score": float(r[3]) if r[3] is not None else 0.0,
        }
        for r in rows
    ]
