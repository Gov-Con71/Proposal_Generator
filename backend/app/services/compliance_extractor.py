import asyncio
import logging
import os
from typing import Literal, Optional, TypedDict

from pydantic import BaseModel
from langgraph.graph import StateGraph, START, END

logger = logging.getLogger(__name__)

_MODEL = "gemini-2.0-flash"
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
    """Single graph node: calls Gemini with structured output to populate ComplianceMatrix."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    api_key = os.environ["GEMINI_API_KEY"]
    llm = ChatGoogleGenerativeAI(model=_MODEL, google_api_key=api_key)
    structured_llm = llm.with_structured_output(ComplianceMatrix)

    prompt = f"{_SYSTEM_PROMPT}\n\nDOCUMENT:\n{state['markdown_text']}"

    logger.info(
        "_extract_compliance_node: sending %d chars of markdown to %s",
        len(state["markdown_text"]),
        _MODEL,
    )
    result: ComplianceMatrix = structured_llm.invoke(prompt)
    logger.info(
        "_extract_compliance_node: received %d requirements from LLM",
        len(result.requirements),
    )

    return {"markdown_text": state["markdown_text"], "requirements": result}


def _build_graph():
    graph = StateGraph(ExtractionState)
    graph.add_node("extract_compliance", _extract_compliance_node)
    graph.add_edge(START, "extract_compliance")
    graph.add_edge("extract_compliance", END)
    return graph.compile()


# Compiled once at import time; reused across calls
_extraction_graph = _build_graph()


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
        _extraction_graph.invoke, initial_state
    )
    return final_state["requirements"]
