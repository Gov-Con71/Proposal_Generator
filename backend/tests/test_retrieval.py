"""Unit tests for Reciprocal Rank Fusion and the metadata pre-filter clause —
the pure, DB-free half of hybrid retrieval (`app/services/retrieval.py`). The
SQL side (dense + keyword legs against real pgvector/tsvector, including the
pre-filter actually narrowing results) is exercised in
`tests/test_workspace_rag.py` against a live Postgres.
"""

from app.services.retrieval import _build_filter_clause, _reciprocal_rank_fusion


def _hit(chunk_id: str, score: float) -> dict:
    return {"chunk_id": chunk_id, "source_name": "s.pdf", "content": "c", "score": score}


def test_rrf_ranks_a_hit_present_in_both_legs_above_a_single_leg_hit():
    """A chunk that's a decent match on both dense and keyword signals should
    outrank one that's a strong match on only one — that's the whole point of
    fusing rather than picking a single leg."""
    dense = [_hit("both", 0.6), _hit("dense-only", 0.9)]
    keyword = [_hit("both", 0.6), _hit("keyword-only", 0.5)]

    fused = _reciprocal_rank_fusion(dense, keyword)

    assert fused[0]["chunk_id"] == "both"


def test_rrf_includes_a_keyword_only_hit_dense_search_missed():
    """The whole motivation: an exact clause/cert/contract-number match that
    isn't a top semantic match on its own must still surface."""
    dense = [_hit("semantic-1", 0.8), _hit("semantic-2", 0.75)]
    keyword = [_hit("exact-match", 0.4)]  # low cosine score, but ranks #1 on keyword

    fused = _reciprocal_rank_fusion(dense, keyword)

    assert {h["chunk_id"] for h in fused} == {"semantic-1", "semantic-2", "exact-match"}


def test_rrf_preserves_the_cosine_score_not_a_fused_score():
    """`score` must stay a plain cosine similarity so callers' min_score floors
    keep meaning what they've always meant — fusion changes ordering/selection,
    never what the score field represents."""
    dense = [_hit("c1", 0.42)]
    keyword: list[dict] = []

    fused = _reciprocal_rank_fusion(dense, keyword)

    assert fused[0]["score"] == 0.42


def test_rrf_handles_an_empty_leg():
    dense = [_hit("c1", 0.5), _hit("c2", 0.4)]
    fused = _reciprocal_rank_fusion(dense, [])
    assert [h["chunk_id"] for h in fused] == ["c1", "c2"]


def test_rrf_handles_both_legs_empty():
    assert _reciprocal_rank_fusion([], []) == []


# --- _build_filter_clause ------------------------------------------------------

def test_filter_clause_empty_when_no_filters_given():
    sql, params = _build_filter_clause(None, None, None)
    assert sql == ""
    assert params == ()


def test_filter_clause_single_filter():
    sql, params = _build_filter_clause("Marine Engineering", None, None)
    assert sql == " AND industry = %s"
    assert params == ("Marine Engineering",)


def test_filter_clause_combines_all_three_in_order():
    sql, params = _build_filter_clause("Marine Engineering", "past_performance", "won")
    assert sql == " AND industry = %s AND document_type = %s AND outcome = %s"
    assert params == ("Marine Engineering", "past_performance", "won")


def test_filter_clause_skips_only_the_omitted_filters():
    sql, params = _build_filter_clause(None, "case_study", "lost")
    assert sql == " AND document_type = %s AND outcome = %s"
    assert params == ("case_study", "lost")
