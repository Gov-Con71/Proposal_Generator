"""
Queue Worker — Document Ingestion Pipeline
==========================================
Mock async worker that drives the full Sprint 2 ingestion sequence:

  1. Accept a file path (simulating an S3 download trigger)
  2. Convert the document to Markdown via document_parser.parse_to_markdown
  3. Run the LangGraph compliance extraction via compliance_extractor.run_extraction
  4. Emit the validated Pydantic JSON to stdout (simulating PostgreSQL ingestion)

Usage:
    GEMINI_API_KEY=... python backend/scripts/queue_worker.py [path/to/document.pdf]

    If no path is supplied the worker runs against a built-in synthetic Markdown
    payload so the end-to-end async hand-offs can be validated without a real file.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ---------------------------------------------------------------------------
# Logging — matches project convention from benchmark_pdf_extraction.py
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# Ensure our backend package is importable when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.document_parser import DocumentParseError, parse_to_markdown
from app.services.compliance_extractor import ComplianceMatrix, run_extraction

# ---------------------------------------------------------------------------
# Synthetic payload — used when no real file is provided
# ---------------------------------------------------------------------------

_SYNTHETIC_MARKDOWN = """\
# Request for Proposal: Cloud Security Platform

## Section 3.1 — Technical Requirements
The vendor SHALL provide a containerised deployment using Kubernetes 1.28 or later.
All microservices MUST expose health-check endpoints on /healthz within 200ms.

## Section 3.2 — Security Requirements
The system SHALL implement AES-256 encryption for all data at rest.
Vendors MUST hold an active FedRAMP Moderate authorisation at time of award.
All privileged access MUST be gated by multi-factor authentication (MFA).

## Section 4.1 — Past Performance
Offerors SHALL provide a minimum of three (3) contracts of similar scope
completed within the past five (5) years with a total contract value of
no less than USD 1,000,000 each.

## Section 4.2 — Technical Deliverables
The vendor SHALL deliver a System Security Plan (SSP) within 30 days of award.
A Contingency Plan and Incident Response Plan are REQUIRED deliverables at Phase 2.
"""


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

async def process_document(file_path: str) -> None:
    """Executes the full ingestion pipeline for a single document."""
    log.info("=== Queue Worker: job received for '%s' ===", file_path)

    # Step 1 — document → Markdown
    log.info("[Step 1/3] Parsing document to Markdown ...")
    try:
        markdown_text = await parse_to_markdown(file_path)
        log.info("[Step 1/3] Markdown conversion complete — %d chars", len(markdown_text))
    except FileNotFoundError:
        log.warning(
            "[Step 1/3] File '%s' not found — falling back to synthetic payload", file_path
        )
        markdown_text = _SYNTHETIC_MARKDOWN
        log.info("[Step 1/3] Synthetic payload loaded — %d chars", len(markdown_text))
    except DocumentParseError as exc:
        log.error("[Step 1/3] Parse failed — %s", exc)
        raise

    # Step 2 — Markdown → ComplianceMatrix via LangGraph
    log.info("[Step 2/3] Running LangGraph compliance extraction workflow ...")
    compliance_matrix: ComplianceMatrix = await run_extraction(markdown_text)
    log.info(
        "[Step 2/3] Extraction complete — %d requirements identified",
        len(compliance_matrix.requirements),
    )

    # Step 3 — emit validated JSON (simulates INSERT INTO compliance_requirements)
    log.info("[Step 3/3] Emitting validated Pydantic JSON (simulated PostgreSQL ingestion) ...")
    output = compliance_matrix.model_dump()
    print("\n" + "=" * 72)
    print("  COMPLIANCE MATRIX — validated output ready for DB insertion")
    print("=" * 72)
    print(json.dumps(output, indent=2))
    print("=" * 72 + "\n")

    log.info(
        "=== Queue Worker: job complete — %d requirements persisted ===",
        len(compliance_matrix.requirements),
    )


async def main() -> None:
    file_path = sys.argv[1] if len(sys.argv) > 1 else "dummy_rfp.pdf"
    log.info("Queue Worker starting — target file: '%s'", file_path)
    await process_document(file_path)


if __name__ == "__main__":
    asyncio.run(main())
