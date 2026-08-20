"""Minimal Markdown → structured blocks, for rendering drafted sections into
non-Markdown export formats (PDF, DOCX, XLSX).

The drafting agent's system prompt (`draft_writer._SECTION_SYSTEM_PROMPT`) asks
the LLM for a small, fixed Markdown vocabulary: ATX headings (`## Heading`),
bullet lists (`- item`), and `**bold**` spans. This is deliberately not a
general Markdown parser — it recognizes exactly that vocabulary and treats
everything else as plain paragraph text, which is what drafted content
actually contains. Before this module existed, every export renderer dumped
the raw Markdown string into a plain-text cell/paragraph, so a delivered PDF
or DOCX literally showed `##`, `-`, and `**` characters instead of rendered
headings, bullets, and bold text.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

# The drafting agent's system prompt asks for exactly these four section
# headings (draft_writer._SECTION_SYSTEM_PROMPT). An LLM occasionally drops a
# formatting marker it was told to use — observed in real drafted content: a
# "## Technical Approach" heading came back as a bare "Technical Approach"
# line, which _HEADING_RE alone doesn't recognize, so it silently rendered as
# an unstyled paragraph instead of a heading. This is deliberately a closed
# set, not a generic "short standalone line" heuristic — a titlecase sentence
# fragment is common in ordinary prose and would be a false positive; these
# four exact titles are not.
_CANONICAL_HEADINGS = {
    "understanding of the requirement",
    "technical approach",
    "management plan",
    "differentiators",
}

# (text, is_bold)
Run = tuple[str, bool]


@dataclass
class Block:
    kind: Literal["heading", "bullet", "paragraph"]
    level: int = 0  # heading depth 1-6; unused for bullet/paragraph
    runs: list[Run] = field(default_factory=list)


def _parse_runs(text: str) -> list[Run]:
    """Splits `text` on `**bold**` spans into (text, is_bold) runs, in order."""
    runs: list[Run] = []
    pos = 0
    for m in _BOLD_RE.finditer(text):
        if m.start() > pos:
            runs.append((text[pos : m.start()], False))
        runs.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], False))
    return runs or [("", False)]


def parse(markdown_text: str) -> list[Block]:
    """Parses drafted Markdown into a flat list of heading/bullet/paragraph blocks.

    Consecutive non-blank plain-text lines are joined into one paragraph block
    (a blank line, a heading, or a bullet each end the current paragraph) —
    the same soft-wrap behavior a Markdown renderer applies to the LLM's
    line-wrapped prose.
    """
    blocks: list[Block] = []
    para_lines: list[str] = []

    def flush_paragraph() -> None:
        if para_lines:
            text = " ".join(para_lines).strip()
            if text:
                blocks.append(Block(kind="paragraph", runs=_parse_runs(text)))
            para_lines.clear()

    for raw_line in (markdown_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            blocks.append(Block(kind="heading", level=level, runs=_parse_runs(heading.group(2).strip())))
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            flush_paragraph()
            blocks.append(Block(kind="bullet", runs=_parse_runs(bullet.group(1).strip())))
            continue

        # Only when this line starts a fresh block (nothing buffered yet) — a
        # canonical title appearing mid-paragraph as a continuation of prose
        # is not a heading, and checking `not para_lines` keeps that case as
        # plain text rather than misfiring on it.
        if not para_lines and line.lower() in _CANONICAL_HEADINGS:
            blocks.append(Block(kind="heading", level=2, runs=_parse_runs(line)))
            continue

        para_lines.append(line)

    flush_paragraph()
    return blocks


def to_plain_text(blocks: list[Block]) -> str:
    """Flattens blocks to clean, readable plain text (Markdown syntax removed,
    bold spans unwrapped) — for targets like an XLSX cell where per-run rich
    formatting isn't worth the complexity but raw `##`/`**` syntax still is."""
    lines = []
    for blk in blocks:
        text = "".join(t for t, _ in blk.runs)
        lines.append(f"• {text}" if blk.kind == "bullet" else text)
    return "\n".join(lines)
