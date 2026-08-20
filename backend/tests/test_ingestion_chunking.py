"""Map-reduce compliance extraction for oversized RFPs (ingestion.py).

`guard_extraction_input` truncates anything over `settings.max_extraction_chars`
and silently drops the document tail — its own docstring calls chunked/
map-reduce extraction "the real fix". `_extract_compliance_matrix` is that fix:
below the budget it's a single call (unchanged behavior); above it, the
document is split via `semantic_chunks` and each chunk is extracted and merged.

These are pure unit tests against `_extract_compliance_matrix` directly (LLM
extraction is stubbed), not a full DB-backed ingestion run.
"""

import asyncio

from app.core.config import settings
from app.services import ingestion
from app.services.compliance_extractor import ComplianceMatrix, ExtractedRequirement
from app.services.guardrails import sanitize_matrix


def _rfp_like_document(n_clauses: int, words_per_clause: int = 30) -> str:
    filler = " ".join(["requirement"] * words_per_clause)
    parts = [
        f"C.{i} Clause {i}\nThe contractor shall {filler} for item {i}."
        for i in range(1, n_clauses + 1)
    ]
    return "\n\n".join(parts)


def test_document_within_budget_takes_a_single_extraction_call(monkeypatch):
    calls = []

    async def fake_extract(markdown_text):
        calls.append(markdown_text)
        return ComplianceMatrix(
            requirements=[
                ExtractedRequirement(
                    section_number="C.1", raw_text_content="Do the thing.", category="Technical"
                )
            ]
        )

    monkeypatch.setattr(ingestion, "run_extraction", fake_extract)

    result = asyncio.run(ingestion._extract_compliance_matrix(None, "a short document"))

    assert calls == ["a short document"]
    assert len(result.requirements) == 1


def test_oversized_document_is_chunked_and_results_merged(monkeypatch):
    monkeypatch.setattr(settings, "max_extraction_chars", 1_000)

    calls = []

    async def fake_extract(markdown_text):
        calls.append(markdown_text)
        idx = len(calls)
        return ComplianceMatrix(
            requirements=[
                ExtractedRequirement(
                    section_number=f"C.{idx}",
                    raw_text_content=f"Requirement from chunk {idx}.",
                    category="Technical",
                )
            ]
        )

    monkeypatch.setattr(ingestion, "run_extraction", fake_extract)

    big_doc = _rfp_like_document(10)
    assert len(big_doc) > settings.max_extraction_chars

    result = asyncio.run(ingestion._extract_compliance_matrix(None, big_doc))

    assert len(calls) > 1  # actually split into multiple chunks, not one oversized call
    assert len(result.requirements) == len(calls)
    texts = {r.raw_text_content for r in result.requirements}
    assert texts == {f"Requirement from chunk {i}." for i in range(1, len(calls) + 1)}


def test_no_chunk_individually_exceeds_the_configured_budget(monkeypatch):
    """Each map-reduce chunk should itself be safely under max_extraction_chars
    — the whole point is that no single LLM call is oversized."""
    monkeypatch.setattr(settings, "max_extraction_chars", 2_000)

    seen_chunk_sizes = []

    async def fake_extract(markdown_text):
        seen_chunk_sizes.append(len(markdown_text))
        return ComplianceMatrix(requirements=[])

    monkeypatch.setattr(ingestion, "run_extraction", fake_extract)

    big_doc = _rfp_like_document(20)
    asyncio.run(ingestion._extract_compliance_matrix(None, big_doc))

    assert len(seen_chunk_sizes) > 1
    assert all(size <= settings.max_extraction_chars for size in seen_chunk_sizes)


def test_duplicate_requirements_from_chunk_overlap_are_deduped_downstream(monkeypatch):
    """_extract_compliance_matrix itself doesn't dedup — sanitize_matrix (run by
    the caller, run_ingestion) is what absorbs a requirement re-extracted from
    more than one chunk. Verify the merged output is exactly what sanitize_matrix
    is designed to clean up."""
    monkeypatch.setattr(settings, "max_extraction_chars", 1_000)

    async def fake_extract(markdown_text):
        # Every chunk "sees" and re-extracts the same boundary requirement.
        return ComplianceMatrix(
            requirements=[
                ExtractedRequirement(
                    section_number="C.1",
                    raw_text_content="Shared boundary requirement text.",
                    category="Technical",
                )
            ]
        )

    monkeypatch.setattr(ingestion, "run_extraction", fake_extract)

    big_doc = _rfp_like_document(10)
    merged = asyncio.run(ingestion._extract_compliance_matrix(None, big_doc))
    assert len(merged.requirements) > 1  # duplicated across chunks, pre-sanitize

    clean, rejected = sanitize_matrix(merged)
    assert len(clean.requirements) == 1
    assert rejected == len(merged.requirements) - 1
