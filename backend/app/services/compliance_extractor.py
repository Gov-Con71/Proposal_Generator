import asyncio
import logging
from typing import Literal, Optional, TypedDict

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a government contracting compliance analyst. "
    "Extract every hard compliance rule, deliverable, and vendor requirement "
    "from the RFP document below. For each item capture: the section number "
    "exactly as it appears, the verbatim requirement text, and classify it as "
    "one of: Technical, Security, or Past Performance."
)


# ---------------------------------------------------------------------------
# Pydantic schemas (mirror the compliance_requirements DB table)
# ---------------------------------------------------------------------------

class ExtractedRequirement(BaseModel):
    section_number: str
    raw_text_content: str
    category: Literal["Technical", "Security", "Past Performance"]


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
