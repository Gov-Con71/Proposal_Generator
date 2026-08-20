"""Vector query + context ranking (Story 3.2).

Embeds a requirement/query and finds the closest historical chunks for the
tenant via pgvector cosine distance, returning ranked context blocks for the
draft writer.

Hybrid search (Story 3.2 follow-up): dense cosine similarity alone
systematically underweights exact-token recall — a FAR/DFARS clause number, a
certification string, or a contract number is exactly the kind of literal
match a paraphrase-tolerant embedding can rank below a merely topically
similar chunk. `search_similar` fuses a keyword (`tsvector`/GIN) leg with the
dense leg via Reciprocal Rank Fusion so a chunk that's the unique exact match
for a term still surfaces even when its overall semantic score is unremarkable.
"""

import logging
from typing import Optional
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


# Reciprocal Rank Fusion constant. 60 is the value from the original RRF paper
# (Cormack et al.) and is not sensitive to tuning — it just controls how much
# a low rank in one leg is discounted, not which leg "wins".
_RRF_K = 60

# Each leg fetches this many candidates before fusion, wider than the final
# top_k so a chunk that's mediocre-but-present in one leg and strong in the
# other still has a chance to be pulled into the fused result.
_FETCH_MULTIPLIER = 3
_MIN_FETCH = 15


def _reciprocal_rank_fusion(*ranked_lists: list[dict]) -> list[dict]:
    """Merges ranked hit lists into one, ordered by summed reciprocal rank.

    A chunk absent from a leg contributes 0 for that leg rather than being
    penalized further — being unranked in the keyword leg (e.g. no exact term
    match) is not evidence against it, just the absence of that signal.
    `score` (cosine similarity) is preserved from whichever leg the chunk was
    seen in first: both legs compute the identical cosine expression, so any
    occurrence's score is equivalent — fusion only changes ordering/selection.
    """
    rrf_scores: dict[str, float] = {}
    by_id: dict[str, dict] = {}
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked, start=1):
            cid = hit["chunk_id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank)
            by_id.setdefault(cid, hit)
    return sorted(by_id.values(), key=lambda h: -rrf_scores[h["chunk_id"]])


def _rows_to_hits(rows, origin: str) -> list[dict]:
    return [
        {
            "chunk_id": str(r[0]),
            "source_name": r[1],
            "content": r[2],
            "score": float(r[3]) if r[3] is not None else 0.0,
            # Which pool the evidence came from, so a caller can say whether a
            # section was grounded in this bid's own documents or the library.
            "origin": origin,
        }
        for r in rows
    ]


def _build_filter_clause(
    industry: str | None, document_type: str | None, outcome: str | None
) -> tuple[str, tuple]:
    """SQL AND-clause (plus its params) for the optional metadata pre-filter.

    Each argument is an exact-match filter, applied before the similarity
    ranking rather than after — a tenant's knowledge base can hold chunks from
    several industries or outcomes, and asking for e.g. only `outcome="won"`
    should shrink the candidate pool the vector/keyword search ranks over, not
    just tag the results after the fact. Omitted (None) filters add nothing,
    so a caller supplying none of the three gets exactly the unfiltered query.
    """
    clauses: list[str] = []
    params: list[str] = []
    for column, value in (("industry", industry), ("document_type", document_type), ("outcome", outcome)):
        if value is not None:
            clauses.append(f"{column} = %s")
            params.append(value)
    if not clauses:
        return "", ()
    return " AND " + " AND ".join(clauses), tuple(params)


def _search_pool(
    cur,
    uploaded_by: UUID,
    query: str,
    query_vec: str,
    fetch_k: int,
    proposal_id: Optional[UUID],
    filter_sql: str,
    filter_params: tuple,
) -> list[dict]:
    """Hybrid search within ONE pool: a proposal's own chunks, or the library.

    `proposal_id` None means the long-term library (`proposal_id IS NULL`), so
    a bid's supporting documents never leak into another bid's retrieval.
    `filter_sql`/`filter_params` (from `_build_filter_clause`) add the optional
    industry/document_type/outcome pre-filter to both legs.
    """
    scope_sql = "proposal_id = %s" if proposal_id else "proposal_id IS NULL"
    scope_arg: tuple = (str(proposal_id),) if proposal_id else ()
    origin = "bid" if proposal_id else "library"

    # Dense leg: semantic proximity — best for paraphrase/register variance.
    cur.execute(
        f"""
        SELECT chunk_id, source_name, content,
               1 - (embedding <=> %s::vector) AS score
        FROM historical_chunks
        WHERE uploaded_by = %s AND embedding IS NOT NULL AND {scope_sql}{filter_sql}
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
        """,
        (query_vec, str(uploaded_by), *scope_arg, *filter_params, query_vec, fetch_k),
    )
    dense_hits = _rows_to_hits(cur.fetchall(), origin)

    # Keyword leg: exact-token recall. Harmlessly empty when the query has no
    # parseable terms (plainto_tsquery on an empty/stopword-only string yields
    # an empty tsquery, which matches nothing).
    cur.execute(
        f"""
        SELECT chunk_id, source_name, content,
               1 - (embedding <=> %s::vector) AS score
        FROM historical_chunks
        WHERE uploaded_by = %s AND embedding IS NOT NULL AND {scope_sql}{filter_sql}
          AND content_tsv @@ plainto_tsquery('english', %s)
        ORDER BY ts_rank(content_tsv, plainto_tsquery('english', %s)) DESC
        LIMIT %s;
        """,
        (query_vec, str(uploaded_by), *scope_arg, *filter_params, query, query, fetch_k),
    )
    keyword_hits = _rows_to_hits(cur.fetchall(), origin)

    return _reciprocal_rank_fusion(dense_hits, keyword_hits)


def search_similar(
    uploaded_by: UUID,
    query: str,
    top_k: int = 5,
    min_score: float = 0.0,
    proposal_id: Optional[UUID] = None,
    *,
    industry: str | None = None,
    document_type: str | None = None,
    outcome: str | None = None,
) -> list[dict]:
    """Returns the top_k most relevant historical chunks for the tenant.

    Hybrid: a dense (cosine similarity) leg and a keyword (`tsvector`) leg are
    each fetched wider than `top_k`, then fused by Reciprocal Rank Fusion so a
    chunk that's the exact match for a clause/cert/contract number surfaces
    even when it isn't a top semantic match on its own. `score` on every
    returned hit is still plain cosine similarity in [0, 1] — fusion changes
    which chunks are selected and their order, never what `score` means, so
    `min_score` keeps its existing meaning for callers.

    `min_score` drops weak matches. Top-k alone returns whatever the tenant
    happens to have, so a sparse corpus yields irrelevant chunks that callers
    then present to the model as evidence — the floor makes "nothing relevant"
    an explicit empty result instead. Defaults to 0.0, preserving the previous
    behaviour for callers that do not opt in.

    `proposal_id` selects the evidence pool. Without it, only the long-term
    library is searched. With it, the bid's OWN supporting documents are
    searched first and the library only tops up the remainder — a user who
    attached documents to this solicitation meant them to win, so they are not
    made to compete on raw similarity against an archive that may be far
    larger. Each hit carries `origin` ("bid" or "library") so callers can tell
    a reviewer where a claim's grounding came from.

    `industry` / `document_type` / `outcome` pre-filter the candidate pool by
    the tags `history_service.store_history` attaches at ingest — e.g. restrict
    a search to one industry, or to chunks tagged `outcome="won"`. All default
    to None (no filtering), so an existing caller's behavior is unchanged.
    """
    if not query.strip():
        return []
    query_vec = _vector_literal(embed_query(query))
    fetch_k = max(top_k * _FETCH_MULTIPLIER, _MIN_FETCH)
    filter_sql, filter_params = _build_filter_clause(industry, document_type, outcome)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            bid_hits: list[dict] = []
            if proposal_id:
                bid_hits = _search_pool(
                    cur, uploaded_by, query, query_vec, fetch_k, proposal_id,
                    filter_sql, filter_params,
                )
                bid_hits = [h for h in bid_hits if h["score"] >= min_score][:top_k]

            # Only reach for the library when the bid's own documents did not
            # fill the budget — including when there are none at all, which is
            # the common case for a user who skipped the upload step.
            remaining = top_k - len(bid_hits)
            library_hits: list[dict] = []
            if remaining > 0:
                library_hits = _search_pool(
                    cur, uploaded_by, query, query_vec, fetch_k, None,
                    filter_sql, filter_params,
                )
                library_hits = [
                    h for h in library_hits if h["score"] >= min_score
                ][:remaining]
    finally:
        conn.close()

    kept = bid_hits + library_hits
    if proposal_id:
        logger.info(
            "search_similar: %d hit(s) — %d from this bid, %d from the library",
            len(kept),
            len(bid_hits),
            len(library_hits),
        )
    else:
        logger.info("search_similar: %d hits for query (%.40s...)", len(kept), query)
    return kept
