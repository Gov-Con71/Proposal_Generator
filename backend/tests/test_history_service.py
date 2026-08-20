"""Past-performance chunking (history_service.chunk_text).

`chunk_text` used to be fixed-size sliding windows, risking a cut between a
heading (e.g. "PROJECT SUMMARY") and the paragraph it introduces. It now
delegates to the heading-aware `semantic_chunker.semantic_chunks` — these
tests exercise that delegation and the specific case it fixes.
"""

from app.services.history_service import chunk_text


def test_short_text_is_a_single_chunk():
    text = "We overhauled centrifugal pumps for the USCG under contract W91QUZ-19-C-0042."
    assert chunk_text(text) == [text]


def test_empty_text_yields_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_heading_stays_attached_to_its_own_paragraph():
    """The failure mode the old fixed-window chunker had: a window boundary
    could land between a section heading and the paragraph describing it."""
    doc = (
        "PROJECT SUMMARY\n"
        + ("Delivered depot-level pump overhauls on schedule. " * 20)
        + "\n\n"
        "KEY PERSONNEL\n"
        + ("Led by a PMP-certified program manager with 15 years in GovCon. " * 20)
    )
    chunks = chunk_text(doc, size=800, overlap=100)

    summary_chunks = [c for c in chunks if "PROJECT SUMMARY" in c]
    assert len(summary_chunks) == 1
    assert "Delivered depot-level pump overhauls" in summary_chunks[0]

    personnel_chunks = [c for c in chunks if "KEY PERSONNEL" in c]
    assert len(personnel_chunks) == 1
    assert "PMP-certified program manager" in personnel_chunks[0]


def test_oversized_unheaded_prose_is_still_chunked_with_overlap():
    """A long narrative paragraph with no heading structure at all — the case
    the old sliding window handled — still gets split, with overlap so a fact
    at the cut point isn't lost from both sides. Content is deliberately
    non-repeating (distinct task-order numbers), so an equal head/tail slice
    can only mean real overlap, not a coincidence of periodic text."""
    narrative = " ".join(f"Delivered task order {i:05d} on schedule." for i in range(200))
    chunks = chunk_text(narrative, size=800, overlap=100)

    assert len(chunks) > 1
    assert all(len(c) <= 800 for c in chunks)
    # Overlap: the tail of one chunk reappears at the head of the next.
    assert chunks[0][-100:] == chunks[1][:100]
