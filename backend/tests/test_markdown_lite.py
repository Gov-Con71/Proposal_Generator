"""Minimal Markdown -> blocks parser (markdown_lite.py) — the fix for export
renderers dumping raw `##`/`-`/`**` Markdown syntax as literal text instead of
rendering it, against the fixed vocabulary the drafting agent's system prompt
actually asks the LLM to produce (ATX headings, bullets, bold spans).
"""

from app.services.markdown_lite import parse, to_plain_text


def test_empty_text_yields_no_blocks():
    assert parse("") == []
    assert parse("   \n  ") == []


def test_plain_paragraph():
    blocks = parse("The contractor shall deliver widgets on schedule.")
    assert len(blocks) == 1
    assert blocks[0].kind == "paragraph"
    assert blocks[0].runs == [("The contractor shall deliver widgets on schedule.", False)]


def test_soft_wrapped_lines_join_into_one_paragraph():
    blocks = parse("Line one of the paragraph\nstill the same paragraph.")
    assert len(blocks) == 1
    assert blocks[0].kind == "paragraph"
    text = "".join(t for t, _ in blocks[0].runs)
    assert text == "Line one of the paragraph still the same paragraph."


def test_blank_line_separates_paragraphs():
    blocks = parse("First paragraph.\n\nSecond paragraph.")
    assert [b.kind for b in blocks] == ["paragraph", "paragraph"]
    assert "".join(t for t, _ in blocks[0].runs) == "First paragraph."
    assert "".join(t for t, _ in blocks[1].runs) == "Second paragraph."


def test_atx_heading_levels():
    blocks = parse("# Level 1\n## Level 2\n###### Level 6")
    assert [(b.kind, b.level) for b in blocks] == [
        ("heading", 1),
        ("heading", 2),
        ("heading", 6),
    ]
    assert blocks[0].runs == [("Level 1", False)]


def test_bullet_list_items_are_separate_blocks():
    blocks = parse("- first item\n- second item\n* third item (asterisk bullet)")
    assert [b.kind for b in blocks] == ["bullet", "bullet", "bullet"]
    assert "".join(t for t, _ in blocks[0].runs) == "first item"
    assert "".join(t for t, _ in blocks[2].runs) == "third item (asterisk bullet)"


def test_bold_span_becomes_a_separate_run():
    blocks = parse("Certified by **CMMC Level 2** for this engagement.")
    assert blocks[0].runs == [
        ("Certified by ", False),
        ("CMMC Level 2", True),
        (" for this engagement.", False),
    ]


def test_multiple_bold_spans_in_one_line():
    blocks = parse("**Feature:** description. **Proof:** contract W91QUZ.")
    runs = blocks[0].runs
    bold_texts = [t for t, b in runs if b]
    assert bold_texts == ["Feature:", "Proof:"]


def test_bold_span_inside_a_heading():
    blocks = parse("## **Differentiators**")
    assert blocks[0].kind == "heading"
    assert blocks[0].runs == [("Differentiators", True)]


def test_bold_span_inside_a_bullet():
    blocks = parse("- **CMMC Level 2** certified since 2023")
    assert blocks[0].kind == "bullet"
    assert blocks[0].runs[0] == ("CMMC Level 2", True)


def test_realistic_drafted_section():
    """The actual shape of content the drafting agent's system prompt asks
    for — the exact case that used to leak raw Markdown into exports."""
    content = (
        "## Understanding of the Requirement\n\n"
        "We understand the need for depot-level pump overhaul services.\n\n"
        "## Technical Approach\n\n"
        "Our approach includes:\n"
        "- Certified technicians perform teardown and inspection\n"
        "- OEM-spec parts sourced from approved vendors\n\n"
        "**Differentiators:** Our team holds an active CMMC Level 2 certification."
    )
    blocks = parse(content)
    kinds = [b.kind for b in blocks]
    assert kinds == [
        "heading", "paragraph", "heading", "paragraph", "bullet", "bullet", "paragraph",
    ]
    assert blocks[0].level == 2
    assert blocks[0].runs == [("Understanding of the Requirement", False)]
    assert blocks[-1].runs[0] == ("Differentiators:", True)

    # No raw Markdown syntax characters survive into any run's text.
    all_text = " ".join(t for b in blocks for t, _ in b.runs)
    assert "##" not in all_text
    assert "**" not in all_text
    assert not all_text.strip().startswith("- ")


# --- canonical heading fallback (a dropped "##" marker) -----------------------

def test_canonical_heading_without_a_hash_marker_is_still_a_heading():
    """Observed in real drafted content: the model dropped the "##" in front
    of one of its own four required section headings."""
    blocks = parse("Some prior paragraph.\n\nTechnical Approach\n\nBody text follows.")
    kinds = [b.kind for b in blocks]
    assert kinds == ["paragraph", "heading", "paragraph"]
    assert blocks[1].runs == [("Technical Approach", False)]
    assert blocks[1].level == 2


def test_all_four_canonical_headings_are_recognized_without_a_marker():
    content = "\n\n".join(
        [
            "Understanding of the Requirement",
            "We understand the requirement.",
            "Technical Approach",
            "Our approach is sound.",
            "Management Plan",
            "Our plan is solid.",
            "Differentiators",
            "We are different.",
        ]
    )
    blocks = parse(content)
    headings = [b for b in blocks if b.kind == "heading"]
    assert {"".join(t for t, _ in b.runs) for b in headings} == {
        "Understanding of the Requirement",
        "Technical Approach",
        "Management Plan",
        "Differentiators",
    }


def test_canonical_heading_text_mid_paragraph_is_not_misdetected():
    """A canonical title's exact words showing up mid-sentence (as a
    continuation of an already-started paragraph) must not be treated as a
    heading — only a line that starts a fresh block qualifies."""
    blocks = parse("Our overall Technical Approach\nbuilds on 20 years of experience.")
    assert len(blocks) == 1
    assert blocks[0].kind == "paragraph"


def test_canonical_heading_match_is_case_insensitive():
    blocks = parse("Prior line.\n\ntechnical approach\n\nMore text.")
    assert blocks[1].kind == "heading"


# --- to_plain_text --------------------------------------------------------------

def test_to_plain_text_strips_markdown_syntax_but_keeps_content():
    content = "## Heading\n\nSome **bold** prose.\n\n- bullet one\n- bullet two"
    text = to_plain_text(parse(content))
    assert "##" not in text
    assert "**" not in text
    assert "Heading" in text
    assert "bold" in text
    assert "• bullet one" in text
    assert "• bullet two" in text


def test_to_plain_text_of_empty_content():
    assert to_plain_text(parse("")) == ""
