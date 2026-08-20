"""Heading-aware semantic chunking.

Originally built for large RFP documents: `extraction_input.
guard_extraction_input` truncates a document that exceeds `settings.
max_extraction_chars` — its own docstring calls that "a safety net, not a
substitute for chunked / map-reduce extraction, which is the real fix for
genuinely large documents." `semantic_chunks` is that real fix for both of
this codebase's chunking needs (RFP map-reduce extraction, and history_
service's past-performance ingestion): it splits text into logical sections
along heading boundaries, keeping a heading and the text it governs together,
rather than cutting on an arbitrary character count — an RFP is built out of
numbered/lettered clauses (`C.3.1`, `SECTION L`, `H.4`) whose section number
a mid-clause cut would silently detach from its own text; past-performance
prose (resumes, case studies) is less rigidly structured but still has real
section breaks (paragraphs, headers like "PROJECT SUMMARY") a fixed window
would ignore just the same.

`overlap_chars` (default 0, i.e. no overlap — right for map-reduce LLM
extraction, where duplicated content just costs extra tokens with no
benefit) exists for the other use: a retrieval/embedding index benefits from
a small window of shared context across a hard cut, so a fact split right at
a chunk boundary still has a chance of being embedded together somewhere.
Overlap only ever applies to `_split_oversized`'s last-resort hard character
cut — a genuine mid-content cut with no natural break point at all; sections
and paragraphs split at their own real boundaries never need it, since
nothing there was cut out of context in the first place.
"""

import re

# Markdown headings (DOCX → MarkItDown emits these); "SECTION L" / "PART II" /
# "ATTACHMENT 3" labels; and numbered/lettered clause headings ("C.3.1 Scope
# of Work", "L.2 Volume Structure") — the conventions government solicitations
# actually use for their own structure.
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
_LABELED_HEADING_RE = re.compile(
    r"^(SECTION|PART|VOLUME|ATTACHMENT|APPENDIX|ANNEX)\s+[A-Z0-9]", re.IGNORECASE
)
_CLAUSE_HEADING_RE = re.compile(
    r"^([A-Z]{1,3}(\.\d+){0,4}|\d+(\.\d+){0,4})[.)]?\s{1,4}[A-Z][A-Za-z0-9 ,/&()'-]{2,90}$"
)

# A chunk this size or smaller needs no splitting at all.
DEFAULT_MAX_CHARS = 120_000
# Adjacent sections are merged up to roughly this size before starting a new
# chunk, so a document with many short clauses doesn't explode into one LLM
# call per clause.
DEFAULT_TARGET_CHARS = 90_000


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False
    if _MD_HEADING_RE.match(stripped):
        return True
    if _LABELED_HEADING_RE.match(stripped):
        return True
    if _CLAUSE_HEADING_RE.match(stripped):
        return True
    # All-caps short line (e.g. "INSTRUCTIONS TO OFFERORS") — a common RFP
    # heading style with no numbering at all.
    letters = [c for c in stripped if c.isalpha()]
    if len(letters) >= 3 and stripped == stripped.upper() and len(stripped) <= 90:
        return True
    return False


def _split_into_sections(text: str) -> list[str]:
    """Splits on detected heading lines; each section keeps its heading."""
    sections: list[list[str]] = [[]]
    for line in text.splitlines():
        if _is_heading(line) and sections[-1]:
            sections.append([line])
        else:
            sections[-1].append(line)
    return ["\n".join(s).strip() for s in sections if any(l.strip() for l in s)]


def _split_oversized(section: str, max_chars: int, overlap_chars: int = 0) -> list[str]:
    """Splits one section that alone exceeds `max_chars`, on paragraph breaks
    first (preserving prose structure) and only hard-cutting a single
    paragraph that is itself over budget. `overlap_chars` — see module
    docstring — applies only to that last-resort hard cut."""
    if len(section) <= max_chars:
        return [section]

    parts: list[str] = []
    buf = ""
    for para in re.split(r"\n\s*\n", section):
        if len(para) > max_chars:
            if buf:
                parts.append(buf)
                buf = ""
            step = max(1, max_chars - overlap_chars)
            parts.extend(para[i : i + max_chars] for i in range(0, len(para), step))
            continue
        if not buf:
            buf = para
        elif len(buf) + 2 + len(para) <= max_chars:
            buf = f"{buf}\n\n{para}"
        else:
            parts.append(buf)
            buf = para
    if buf:
        parts.append(buf)
    return parts


def semantic_chunks(
    text: str,
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = 0,
) -> list[str]:
    """Splits `text` into logical, heading-respecting chunks.

    A no-op (single chunk) when `text` already fits within `max_chars` — the
    common case. Otherwise: split into heading-delimited sections, hard-split
    any single section still over `max_chars` on paragraph boundaries, then
    greedily merge adjacent sections up to `target_chars` per chunk so a
    document with many short clauses doesn't explode into one chunk per clause.

    `overlap_chars` (default 0) only affects a paragraph so large it must be
    hard-cut with no natural break point — see module docstring.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sections = _split_into_sections(text) or [text]
    expanded = [
        piece
        for section in sections
        for piece in _split_oversized(section, max_chars, overlap_chars)
    ]

    chunks: list[str] = []
    buf = ""
    for section in expanded:
        if not buf:
            buf = section
        elif len(buf) + 2 + len(section) <= target_chars:
            buf = f"{buf}\n\n{section}"
        else:
            chunks.append(buf)
            buf = section
    if buf:
        chunks.append(buf)
    return chunks
