"""Context-aware draft writer (Story 3.5).

Compiles a requirement plus the tenant's most relevant past-performance context
into drafted proposal prose using google-genai. This is the RAG generation step:
retrieve (3.2) → assemble prompt → generate.
"""

import logging
import os
from uuid import UUID

from app.services.guardrails import validate_draft
from app.services.retrieval import search_similar

logger = logging.getLogger(__name__)

_MODEL = "gemini-2.0-flash"
_SYSTEM_PROMPT = (
    "You are a senior government-contracts proposal writer. Draft a concise, "
    "compliant, professional response to the requirement below. Ground every "
    "claim in the provided past-performance context; do not invent facts, "
    "certifications, or contract numbers. If the context is insufficient, write "
    "a defensible response and note assumptions succinctly."
)


def _assemble_prompt(requirement_text: str, context: list[dict]) -> str:
    if context:
        blocks = "\n\n".join(
            f"[{c['source_name']} — relevance {c['score']:.2f}]\n{c['content']}"
            for c in context
        )
    else:
        blocks = "(no matching past-performance context found)"
    return (
        f"REQUIREMENT:\n{requirement_text}\n\n"
        f"PAST-PERFORMANCE CONTEXT:\n{blocks}\n\n"
        "Write the proposal-section draft now."
    )


def generate_draft(uploaded_by: UUID, requirement_text: str, top_k: int = 5) -> dict:
    """Retrieves context and generates a draft. Returns the prose + citations."""
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set; cannot generate a draft.")

    context = search_similar(uploaded_by, requirement_text, top_k=top_k)
    prompt = _assemble_prompt(requirement_text, context)

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=_SYSTEM_PROMPT),
    )
    # Guardrail: reject empty/degenerate generations before they reach the DB.
    draft = validate_draft(response.text or "")
    logger.info(
        "generate_draft: produced %d chars from %d context block(s)",
        len(draft),
        len(context),
    )
    return {
        "content": draft,
        "citations": [
            {"source_name": c["source_name"], "score": c["score"]} for c in context
        ],
    }
