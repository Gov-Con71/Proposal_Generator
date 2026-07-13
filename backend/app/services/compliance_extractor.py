import asyncio
import logging
import os
from typing import Literal, Optional, TypedDict

from pydantic import BaseModel

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
    """Single graph node: calls Gemini (google-genai SDK) with structured output."""
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set; cannot run compliance extraction.")

    from app.core import telemetry

    client = genai.Client(api_key=api_key)

    logger.info(
        "_extract_compliance_node: sending %d chars of markdown to %s",
        len(state["markdown_text"]),
        _MODEL,
    )
    _start = telemetry.now()
    try:
        response = client.models.generate_content(
            model=_MODEL,
            contents=f"DOCUMENT:\n{state['markdown_text']}",
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=ComplianceMatrix,
            ),
        )
    except Exception:
        telemetry.record_error(_MODEL, _start)
        raise
    telemetry.record_response(_MODEL, response, _start)

    # google-genai parses the JSON straight into the Pydantic schema.
    result: ComplianceMatrix = response.parsed
    if result is None:
        raise RuntimeError("Gemini returned no parseable ComplianceMatrix.")
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
