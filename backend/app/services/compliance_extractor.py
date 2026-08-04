import asyncio
import logging
from typing import Literal, Optional, TypedDict

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a government contracting compliance analyst. "
    "Extract every hard compliance rule, deliverable, and vendor requirement "
    "from the RFP document below. For each item capture: the section number "
    "exactly as it appears, the verbatim requirement text, and its category.\n"
    "Categories:\n"
    "  Technical — what the contractor must do, build, or deliver.\n"
    "  Security — clearances, safeguarding, cyber/CMMC, physical security.\n"
    "  Past Performance — prior-contract experience the offeror must evidence.\n"
    "  Instruction — Section L 'Instructions to Offerors': how the proposal must "
    "be prepared and submitted (volume structure, page limits, format, fonts, "
    "due dates, submission portal, required forms).\n"
    "  Evaluation Criteria — Section M 'Evaluation Factors for Award': what the "
    "government will score the proposal on, and the relative importance of each "
    "factor.\n"
    "Do not skip Sections L and M: a proposal that ignores them is non-responsive, "
    "so extract those rules as diligently as the technical ones."
)


# ---------------------------------------------------------------------------
# Pydantic schemas (mirror the compliance_requirements DB table)
# ---------------------------------------------------------------------------

# `Instruction` (Section L) and `Evaluation Criteria` (Section M) are not things
# the proposal *answers* — they govern how it is written and how it is scored, so
# the drafting agent treats them as cross-cutting constraints rather than as
# requirements to assign to a section. The DB column is a bare VARCHAR(100) with
# no CHECK constraint, so widening the Literal below needs no migration.
INSTRUCTION_CATEGORY = "Instruction"
EVALUATION_CATEGORY = "Evaluation Criteria"
# The categories a proposal section is written to satisfy.
ANSWERABLE_CATEGORIES = frozenset({"Technical", "Security", "Past Performance"})


class ExtractedRequirement(BaseModel):
    section_number: str
    raw_text_content: str
    category: Literal["Technical", "Security", "Past Performance", "Instruction", "Evaluation Criteria"]


class ComplianceMatrix(BaseModel):
    requirements: list[ExtractedRequirement]


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------

class ExtractionState(TypedDict):
    markdown_text: str
    requirements: Optional[ComplianceMatrix]


# ---------------------------------------------------------------------------
# Graph definition
# ---------------------------------------------------------------------------

def _extract_compliance_node(state: ExtractionState) -> ExtractionState:
    """Single graph node: structured extraction via the configured LLM provider."""
    from app.services.extraction_input import guard_extraction_input
    from app.services.llm import get_llm

    document = guard_extraction_input(state["markdown_text"], label="compliance extraction")
    logger.info(
        "_extract_compliance_node: sending %d chars of markdown to the LLM",
        len(document),
    )
    result: ComplianceMatrix = get_llm().generate_structured(
        f"DOCUMENT:\n{document}",
        ComplianceMatrix,
        system=_SYSTEM_PROMPT,
    )
    logger.info(
        "_extract_compliance_node: received %d requirements from LLM",
        len(result.requirements),
    )
    return {"markdown_text": state["markdown_text"], "requirements": result}


def _build_graph():
    # Imported lazily so this module stays import-safe without the langgraph
    # stack installed (keeps it out of the API import chain and unit tests).
    from langgraph.graph import StateGraph, START, END

    graph = StateGraph(ExtractionState)
    graph.add_node("extract_compliance", _extract_compliance_node)
    graph.add_edge(START, "extract_compliance")
    graph.add_edge("extract_compliance", END)
    return graph.compile()


# Compiled once on first use, then reused across calls.
_extraction_graph = None


def _get_graph():
    global _extraction_graph
    if _extraction_graph is None:
        _extraction_graph = _build_graph()
    return _extraction_graph


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_extraction(markdown_text: str) -> ComplianceMatrix:
    """Runs the LangGraph compliance extraction workflow against a Markdown document.

    Returns a validated ComplianceMatrix Pydantic model ready for DB insertion.
    """
    initial_state: ExtractionState = {
        "markdown_text": markdown_text,
        "requirements": None,
    }
    # LangGraph invoke is synchronous; bridge to the event loop via to_thread
    final_state: ExtractionState = await asyncio.to_thread(
        _get_graph().invoke, initial_state
    )
    requirements = final_state.get("requirements")
    if requirements is None:
        raise RuntimeError("Compliance extraction completed without producing requirements.")
    return requirements
