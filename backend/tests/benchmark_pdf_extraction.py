"""
PDF Extraction Benchmarking Script
===================================
Compares PyMuPDF vs pdfplumber for extraction speed and text quality
against a generated multi-page sample document.

Also runs a small async suite of LLM endpoint calls to establish a
baseline for prompt execution latency (round-trip, non-streaming).

Usage:
    GEMINI_API_KEY=... python backend/tests/benchmark_pdf_extraction.py

Dependencies (see requirements.txt):
    pip install -r backend/requirements.txt
"""

import asyncio
import io
import json
import logging
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env from the backend directory, wherever the script is invoked from
load_dotenv(Path(__file__).parents[2] / ".env")


# ---------------------------------------------------------------------------
# Logging — writes to both stdout and a timestamped log file
# ---------------------------------------------------------------------------

_LOG_DIR = Path(__file__).parent / "benchmark_logs"
_LOG_DIR.mkdir(exist_ok=True)
_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = _LOG_DIR / f"pdf_benchmark_{_TS}.log"
JSON_FILE = _LOG_DIR / f"pdf_benchmark_{_TS}.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ExtractionResult:
    library: str
    pages: int
    elapsed_seconds: float
    char_count: int
    word_count: int
    unique_word_ratio: float
    avg_words_per_page: float
    # Fraction of characters that are neither alpha nor whitespace
    noise_ratio: float
    text_sample: str  # first 300 chars, collapsed newlines


@dataclass
class LLMLatencyResult:
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_elapsed_s: float
    tokens_per_second: float
    success: bool
    error: Optional[str]


# ---------------------------------------------------------------------------
# Sample PDF generation (fpdf2)
# ---------------------------------------------------------------------------

_PAGES = [
    (
        "Executive Summary",
        (
            "This proposal outlines a comprehensive approach to modernising the client's "
            "data infrastructure through cloud-native technologies and AI-driven automation. "
            "Our team brings over a decade of experience delivering mission-critical systems "
            "to enterprises across East Africa and beyond. The engagement is structured in "
            "three phases and is designed to minimise disruption to ongoing operations while "
            "delivering measurable value at each milestone."
        ),
    ),
    (
        "Problem Statement",
        (
            "The client currently operates a fragmented set of on-premise data systems that "
            "lack real-time analytics capabilities, incur high operational costs, and are "
            "unable to scale to meet growing demand. Manual processes account for an estimated "
            "40 percent of staff time, creating bottlenecks in reporting and decision-making "
            "cycles. Legacy ETL jobs fail silently two to three times per week, requiring "
            "manual intervention and producing reports that are up to 48 hours stale."
        ),
    ),
    (
        "Proposed Solution",
        (
            "We propose a three-phase migration to a cloud-native architecture built on "
            "managed Kubernetes, a streaming data pipeline using Apache Kafka, and a "
            "vector-search layer for semantic document retrieval. The AI layer will use "
            "retrieval-augmented generation to surface insights from unstructured documents, "
            "reducing analyst time per report by an estimated 60 percent. All infrastructure "
            "will be defined as code using Terraform, enabling repeatable deployments and "
            "a clear audit trail for compliance purposes."
        ),
    ),
    (
        "Technical Architecture",
        (
            "The core architecture consists of an ingestion layer, a transformation layer, "
            "a serving layer, and an AI inference layer. The ingestion layer handles structured "
            "data from relational databases and semi-structured data from REST APIs and event "
            "streams. Transformation is handled by dbt running on Apache Airflow with daily "
            "and hourly DAG schedules. The serving layer exposes a GraphQL API consumed by the "
            "client's existing frontend applications and third-party BI tools including "
            "Metabase and Tableau."
        ),
    ),
    (
        "Budget and Timeline",
        (
            "Phase 1 — Discovery and Design — 4 weeks — USD 18,000. "
            "Phase 2 — Core Infrastructure — 10 weeks — USD 65,000. "
            "Phase 3 — AI Layer and Handover — 6 weeks — USD 42,000. "
            "Total project value: USD 125,000 over 20 weeks. "
            "Payment milestones are tied to delivery of working software at the end of each "
            "phase. A 10 percent retention is held until 30 days post go-live with no "
            "critical bugs outstanding."
        ),
    ),
]


def generate_sample_pdf() -> bytes:
    """Return bytes of a 5-page PDF built from _PAGES using fpdf2."""
    try:
        from fpdf import FPDF
    except ImportError:
        log.error("fpdf2 is not installed — run: pip install fpdf2")
        raise

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    for idx, (title, body) in enumerate(_PAGES):
        pdf.add_page()

        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, f"Page {idx + 1}: {title}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        pdf.set_font("Helvetica", size=11)
        # Repeat body text several times to simulate realistic page density
        for _ in range(5):
            pdf.multi_cell(0, 7, body)
            pdf.ln(2)

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Extraction benchmarks
# ---------------------------------------------------------------------------

def _quality_metrics(text: str, pages: int, elapsed: float, library: str) -> ExtractionResult:
    words = text.split()
    word_count = len(words)
    char_count = len(text)
    unique_words = {w.lower().strip(".,;:!?\"'()[]") for w in words}
    unique_ratio = len(unique_words) / word_count if word_count else 0.0
    alpha_ws = sum(1 for c in text if c.isalpha() or c.isspace())
    noise_ratio = 1.0 - (alpha_ws / char_count) if char_count else 0.0
    avg_wpg = word_count / pages if pages else 0.0
    sample = text[:300].replace("\n", " ")

    return ExtractionResult(
        library=library,
        pages=pages,
        elapsed_seconds=round(elapsed, 6),
        char_count=char_count,
        word_count=word_count,
        unique_word_ratio=round(unique_ratio, 4),
        avg_words_per_page=round(avg_wpg, 1),
        noise_ratio=round(noise_ratio, 4),
        text_sample=sample,
    )


def benchmark_pymupdf(pdf_bytes: bytes) -> ExtractionResult:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        log.error("pymupdf is not installed — run: pip install pymupdf")
        raise

    t0 = time.perf_counter()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = doc.page_count
    full_text = "\n".join(page.get_text() for page in doc)
    doc.close()
    elapsed = time.perf_counter() - t0

    return _quality_metrics(full_text, pages, elapsed, "pymupdf")


def benchmark_pdfplumber(pdf_bytes: bytes) -> ExtractionResult:
    try:
        import pdfplumber
    except ImportError:
        log.error("pdfplumber is not installed — run: pip install pdfplumber")
        raise

    t0 = time.perf_counter()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = len(pdf.pages)
        full_text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    elapsed = time.perf_counter() - t0

    return _quality_metrics(full_text, pages, elapsed, "pdfplumber")


# ---------------------------------------------------------------------------
# LLM latency baseline (Google Gemini SDK, non-streaming)
# ---------------------------------------------------------------------------

_MODEL = "gemini-2.0-flash"
_PROMPT = (
    "Summarise the key components of a strong business proposal "
    "in exactly three concise bullet points."
)


async def _single_llm_call(client: "genai.Client") -> LLMLatencyResult:
    t0 = time.perf_counter()
    try:
        response = await client.aio.models.generate_content(
            model=_MODEL,
            contents=_PROMPT,
        )
        elapsed = time.perf_counter() - t0
        usage = response.usage_metadata
        prompt_tokens = usage.prompt_token_count or 0
        completion_tokens = usage.candidates_token_count or 0
        tps = completion_tokens / elapsed if elapsed > 0 else 0.0
        return LLMLatencyResult(
            model=_MODEL,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_elapsed_s=round(elapsed, 4),
            tokens_per_second=round(tps, 2),
            success=True,
            error=None,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return LLMLatencyResult(
            model=_MODEL,
            prompt_tokens=0,
            completion_tokens=0,
            total_elapsed_s=round(elapsed, 4),
            tokens_per_second=0.0,
            success=False,
            error=str(exc),
        )


async def measure_llm_latency(api_key: str, runs: int = 3) -> list[LLMLatencyResult]:
    """Fire `runs` sequential calls and record round-trip latency for each."""
    try:
        from google import genai
    except ImportError:
        log.error("google-genai is not installed — run: pip install google-genai")
        raise

    client = genai.Client(api_key=api_key)
    results: list[LLMLatencyResult] = []

    for i in range(runs):
        log.info("  LLM run %d/%d ...", i + 1, runs)
        result = await _single_llm_call(client)
        log.info(
            "    elapsed=%.4fs | %d→%d tokens | %.1f tok/s | %s",
            result.total_elapsed_s,
            result.prompt_tokens,
            result.completion_tokens,
            result.tokens_per_second,
            "OK" if result.success else f"FAILED: {result.error}",
        )
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

_SEP = "=" * 72


def _extraction_section(results: list[ExtractionResult]) -> list[str]:
    lines = ["", "## PDF EXTRACTION RESULTS", ""]
    for r in results:
        lines += [
            f"  Library           : {r.library}",
            f"  Pages processed   : {r.pages}",
            f"  Elapsed (s)       : {r.elapsed_seconds:.6f}",
            f"  Characters        : {r.char_count:,}",
            f"  Words             : {r.word_count:,}",
            f"  Avg words / page  : {r.avg_words_per_page}",
            f"  Unique word ratio : {r.unique_word_ratio:.4f}",
            f"  Noise ratio       : {r.noise_ratio:.4f}  (non-alpha-ws chars / total)",
            f"  Text sample       : {r.text_sample!r}",
            "",
        ]

    if len(results) == 2:
        a, b = results
        if a.elapsed_seconds and b.elapsed_seconds:
            speedup = b.elapsed_seconds / a.elapsed_seconds
            winner = a.library if a.elapsed_seconds < b.elapsed_seconds else b.library
            lines += [
                "## EXTRACTION COMPARISON",
                f"  Speed winner      : {winner}",
                f"  Speed ratio       : {max(speedup, 1/speedup):.2f}x  "
                f"({'  {a.library} faster' if a.elapsed_seconds < b.elapsed_seconds else f'  {b.library} faster'})",
                f"  Char delta        : {abs(a.char_count - b.char_count):,} chars",
                f"  Word delta        : {abs(a.word_count - b.word_count):,} words",
                f"  Noise delta       : {abs(a.noise_ratio - b.noise_ratio):.4f}",
                "",
            ]
    return lines


def _llm_section(results: list[LLMLatencyResult]) -> list[str]:
    lines = [
        "## LLM LATENCY BASELINE",
        f"  Model             : {_MODEL}",
        f"  Prompt            : {_PROMPT!r}",
        f"  Runs              : {len(results)}",
        "",
    ]
    successful = [r for r in results if r.success]
    for i, r in enumerate(results, 1):
        status = "OK" if r.success else f"FAILED: {r.error}"
        lines.append(
            f"  Run {i}: {r.total_elapsed_s:.4f}s | "
            f"{r.prompt_tokens}→{r.completion_tokens} tokens | "
            f"{r.tokens_per_second:.1f} tok/s | {status}"
        )

    if successful:
        latencies = [r.total_elapsed_s for r in successful]
        lines += [
            "",
            f"  Mean latency      : {statistics.mean(latencies):.4f}s",
            f"  Median latency    : {statistics.median(latencies):.4f}s",
        ]
        if len(latencies) > 1:
            lines.append(f"  Stdev latency     : {statistics.stdev(latencies):.4f}s")
        lines.append(f"  Min / Max         : {min(latencies):.4f}s / {max(latencies):.4f}s")
    elif results:
        lines.append("  All LLM runs failed — check GEMINI_API_KEY and network.")

    lines.append("")
    return lines


def write_report(
    extraction_results: list[ExtractionResult],
    llm_results: list[LLMLatencyResult],
) -> None:
    header = [
        _SEP,
        "  PDF EXTRACTION & LLM LATENCY BENCHMARK",
        f"  Run at : {datetime.now().isoformat()}",
        f"  Log    : {LOG_FILE}",
        _SEP,
    ]
    body = (
        header
        + _extraction_section(extraction_results)
        + _llm_section(llm_results)
        + [_SEP]
    )
    report_text = "\n".join(body)

    # Overwrite the log file with the final structured report
    LOG_FILE.write_text(report_text + "\n")

    JSON_FILE.write_text(
        json.dumps(
            {
                "timestamp": datetime.now().isoformat(),
                "extraction": [asdict(r) for r in extraction_results],
                "llm_latency": [asdict(r) for r in llm_results],
            },
            indent=2,
        )
    )

    log.info("Report written to %s", LOG_FILE)
    log.info("JSON data written to %s", JSON_FILE)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        log.warning("GEMINI_API_KEY not set — LLM latency benchmark will be skipped.")

    log.info("Generating 5-page sample PDF ...")
    pdf_bytes = generate_sample_pdf()
    log.info("Sample PDF size: %d bytes (%.1f KB)", len(pdf_bytes), len(pdf_bytes) / 1024)

    log.info("Benchmarking PyMuPDF ...")
    pymupdf_result = benchmark_pymupdf(pdf_bytes)
    log.info(
        "  PyMuPDF  → %.6fs | %d words | noise=%.4f",
        pymupdf_result.elapsed_seconds,
        pymupdf_result.word_count,
        pymupdf_result.noise_ratio,
    )

    log.info("Benchmarking pdfplumber ...")
    pdfplumber_result = benchmark_pdfplumber(pdf_bytes)
    log.info(
        "  pdfplumber → %.6fs | %d words | noise=%.4f",
        pdfplumber_result.elapsed_seconds,
        pdfplumber_result.word_count,
        pdfplumber_result.noise_ratio,
    )

    llm_results: list[LLMLatencyResult] = []
    if api_key:
        log.info("Measuring LLM latency (%s, 3 runs) ...", _MODEL)
        llm_results = await measure_llm_latency(api_key, runs=3)
    else:
        log.info("Skipping LLM latency benchmark.")

    write_report([pymupdf_result, pdfplumber_result], llm_results)


if __name__ == "__main__":
    asyncio.run(main())
