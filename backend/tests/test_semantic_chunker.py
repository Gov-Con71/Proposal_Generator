"""Heading-aware semantic chunking (semantic_chunker.py) — the map-reduce
extraction fix for RFPs that exceed `settings.max_extraction_chars`.
"""

from app.services.semantic_chunker import _is_heading, semantic_chunks


# --- _is_heading --------------------------------------------------------------

def test_recognizes_markdown_heading():
    assert _is_heading("## Technical Approach")


def test_recognizes_section_label():
    assert _is_heading("SECTION L - INSTRUCTIONS TO OFFERORS")
    assert _is_heading("PART II")
    assert _is_heading("ATTACHMENT 3")


def test_recognizes_numbered_clause_heading():
    assert _is_heading("C.3.1 Scope of Work")
    assert _is_heading("L.2 Volume Structure")
    assert _is_heading("3.2 Technical Approach")


def test_recognizes_all_caps_heading():
    assert _is_heading("EVALUATION FACTORS FOR AWARD")


def test_rejects_ordinary_prose_line():
    assert not _is_heading("The contractor shall deliver widgets on schedule.")
    assert not _is_heading("")
    assert not _is_heading("   ")


def test_rejects_overly_long_line_even_if_all_caps():
    long_line = "THIS IS AN UNUSUALLY LONG LINE OF ALL CAPS TEXT THAT " * 3
    assert not _is_heading(long_line)


# --- semantic_chunks ----------------------------------------------------------

def test_short_text_returns_single_chunk_unchanged():
    text = "SECTION C\nC.1 Scope\nDo the work."
    assert semantic_chunks(text) == [text]


def test_empty_text_returns_no_chunks():
    assert semantic_chunks("") == []
    assert semantic_chunks("   \n  ") == []


def _rfp_like_document(n_clauses: int, words_per_clause: int = 30) -> str:
    """Each clause is deliberately small (~400 chars) so it never itself exceeds
    the small max_chars used in these tests — only the *document* is oversized,
    which is the case the heading-boundary logic (not the paragraph hard-split
    fallback) is meant to handle."""
    filler = " ".join(["requirement"] * words_per_clause)
    parts = []
    for i in range(n_clauses):
        parts.append(f"C.{i + 1} Clause {i + 1}\nThe contractor shall {filler} for item {i + 1}.")
    return "\n\n".join(parts)


def test_oversized_document_is_split_into_multiple_chunks():
    doc = _rfp_like_document(30)
    assert len(doc) > 4_000
    chunks = semantic_chunks(doc, target_chars=3_000, max_chars=4_000)
    assert len(chunks) > 1
    # Every chunk stays within the hard ceiling.
    assert all(len(c) <= 4_000 for c in chunks)


def test_heading_stays_attached_to_its_own_content():
    doc = _rfp_like_document(10)
    chunks = semantic_chunks(doc, target_chars=2_000, max_chars=2_500)
    for i in range(10):
        heading = f"C.{i + 1} Clause {i + 1}"
        matching = [c for c in chunks if heading in c]
        assert len(matching) == 1, f"heading {heading!r} should appear in exactly one chunk"
        # The clause's own body text is in the same chunk as its heading.
        assert f"for item {i + 1}." in matching[0]


def test_no_content_is_lost_across_chunks():
    doc = _rfp_like_document(15)
    chunks = semantic_chunks(doc, target_chars=2_500, max_chars=3_000)
    reassembled = "\n\n".join(chunks)
    for i in range(15):
        assert f"C.{i + 1} Clause {i + 1}" in reassembled
        assert f"for item {i + 1}." in reassembled


def test_oversized_single_section_with_no_headings_is_split_on_paragraphs():
    # One giant unheaded block (e.g. a scanned narrative page) — no heading
    # boundaries to split on, so it falls back to paragraph breaks.
    paragraphs = [f"Paragraph {i} " + ("word " * 200) for i in range(10)]
    doc = "\n\n".join(paragraphs)
    chunks = semantic_chunks(doc, target_chars=1_500, max_chars=2_000)
    assert len(chunks) > 1
    assert all(len(c) <= 2_000 for c in chunks)


def test_single_paragraph_larger_than_max_chars_is_hard_split():
    huge_paragraph = "word " * 5_000  # no blank lines to split on at all
    chunks = semantic_chunks(huge_paragraph, target_chars=1_000, max_chars=1_000)
    assert len(chunks) > 1
    assert all(len(c) <= 1_000 for c in chunks)


# --- overlap_chars: only applies to the last-resort hard cut -------------------

def _numbered_words(n: int) -> str:
    """Distinguishable content (unlike a repeated "word ") so overlap/no-overlap
    at a hard-cut boundary is actually visible in the output."""
    return " ".join(f"w{i:05d}" for i in range(n))


def test_overlap_is_zero_by_default():
    huge_paragraph = _numbered_words(2_000)
    chunks = semantic_chunks(huge_paragraph, target_chars=1_000, max_chars=1_000)
    # Adjacent hard-cut chunks share no trailing/leading text by default.
    assert chunks[0][-20:] != chunks[1][:20]


def test_overlap_repeats_trailing_context_across_a_hard_cut():
    huge_paragraph = _numbered_words(2_000)
    chunks = semantic_chunks(
        huge_paragraph, target_chars=1_000, max_chars=1_000, overlap_chars=100
    )
    assert len(chunks) > 1
    # The tail of one hard-cut chunk reappears at the head of the next.
    assert chunks[0][-100:] == chunks[1][:100]


def test_overlap_does_not_apply_between_natural_section_boundaries():
    """Two distinct headed sections, each within budget on its own, must not
    gain artificial overlap — only a genuine mid-content hard cut needs it."""
    doc = (
        "C.1 Scope\n" + ("alpha " * 50) + "\n\n"
        "C.2 Deliverables\n" + ("beta " * 50)
    )
    chunks = semantic_chunks(doc, target_chars=50, max_chars=400, overlap_chars=50)
    assert len(chunks) == 2
    assert "C.1 Scope" in chunks[0] and "C.2 Deliverables" not in chunks[0]
    assert "C.2 Deliverables" in chunks[1] and "C.1 Scope" not in chunks[1]
