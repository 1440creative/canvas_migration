#!/usr/bin/env python3
# canvas_calibrator/run_calibration.py
"""
Canvas Calibrator — course content auditing tool.

Usage:
  python canvas_calibrator/run_calibration.py \\
    --course-id 4031 \\
    --quiz-zip path/to/quiz_export.zip \\
    --export-dir export/data/cloud/4031 \\
    --output-dir canvas_calibrator/reports/

Options:
  --skip-fetch      Skip external URL fetching (use cached only)
  --no-pdfs         Skip PDF ingestion
  --rebuild-index   Force re-embed even if cache exists
  --dry-run         Parse and index only, don't call the Claude API
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure repo root is on sys.path
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load .env.local for ANTHROPIC_API_KEY etc.
try:
    from dotenv import load_dotenv
    load_dotenv(str(REPO_ROOT / ".env"))
    load_dotenv(str(REPO_ROOT / ".env.local"), override=True)
except ImportError:
    pass


def main() -> int:
    p = argparse.ArgumentParser(
        description="Canvas Calibrator — audit course content against quiz questions"
    )
    p.add_argument("--course-id", required=True, help="Canvas course ID (used for cache naming)")
    p.add_argument("--quiz-zip", required=True, type=Path, help="Path to New Quizzes QTI zip")
    p.add_argument(
        "--export-dir",
        required=True,
        type=Path,
        help="Course export directory (e.g. export/data/cloud/4031)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("canvas_calibrator/reports"),
        help="Directory to write calibration_report.md/.html (default: canvas_calibrator/reports/)",
    )
    p.add_argument("--skip-fetch", action="store_true", help="Skip external URL fetching")
    p.add_argument("--no-pdfs", action="store_true", help="Skip PDF ingestion")
    p.add_argument("--rebuild-index", action="store_true", help="Force re-embed even if cache exists")
    p.add_argument("--dry-run", action="store_true", help="Parse and index only, no API calls")
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args()

    # Logging
    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")

    log = logging.getLogger("calibrator")

    # --- Step 1: Parse QTI zip ---
    print(f"[1/5] Parsing QTI zip: {args.quiz_zip}")
    from canvas_calibrator.parsers.qti_parser import parse_qti_zip
    questions = parse_qti_zip(args.quiz_zip)
    quiz_title = questions[0]["quiz_title"] if questions else "Unknown Quiz"
    print(f"      → {len(questions)} questions parsed  (quiz: {quiz_title})")

    if not questions:
        print("ERROR: No questions found in zip. Aborting.")
        return 1

    # --- Step 2: Load course content ---
    print(f"[2/5] Loading course content from: {args.export_dir}")
    from canvas_calibrator.ingest.content_loader import load_course_content
    docs = load_course_content(
        args.export_dir,
        skip_fetch=args.skip_fetch,
        no_pdfs=args.no_pdfs,
    )
    print(f"      → {len(docs)} documents loaded")

    extractable = [d for d in docs if d.extractable and d.text.strip()]
    print(f"      → {len(extractable)} extractable documents")

    # --- Step 3: Chunk + Embed ---
    print(f"[3/5] Chunking and embedding documents")
    from canvas_calibrator.rag.chunker import chunk_documents
    chunks = chunk_documents(docs)
    print(f"      → {len(chunks)} chunks created")

    cache_dir = REPO_ROOT / "canvas_calibrator" / ".cache"
    from canvas_calibrator.rag.embedder import embed_chunks
    embeddings, indexed_chunks = embed_chunks(
        chunks,
        course_id=args.course_id,
        cache_dir=cache_dir,
        rebuild=args.rebuild_index,
    )
    print(f"      → {len(indexed_chunks)} chunks embedded")

    from canvas_calibrator.rag.retriever import Retriever
    retriever = Retriever(embeddings, indexed_chunks)

    if args.dry_run:
        print("[4/5] DRY RUN — skipping Claude API calls")
    else:
        print(f"[4/5] Running learner agent ({len(questions)} questions)…")

    # --- Step 4: Run learner agent ---
    from canvas_calibrator.agent.learner import run_learner
    results = run_learner(questions, retriever, dry_run=args.dry_run)

    # Summary
    correct = sum(1 for r in results if r.verdict == "correct")
    wrong = sum(1 for r in results if r.verdict == "wrong")
    unsupported = sum(1 for r in results if r.verdict == "unsupported")
    total = len(results)
    print(f"      → {correct}/{total} correct  |  {wrong} wrong  |  {unsupported} unsupported")

    # --- Step 5: Generate report ---
    print(f"[5/5] Generating report in: {args.output_dir}")
    from canvas_calibrator.report.generator import generate_report
    md_path, html_path = generate_report(
        results,
        course_id=args.course_id,
        quiz_title=quiz_title,
        output_dir=args.output_dir,
    )
    print(f"      → {md_path}")
    print(f"      → {html_path}")
    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
