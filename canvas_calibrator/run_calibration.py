#!/usr/bin/env python3
# canvas_calibrator/run_calibration.py
"""
Canvas Calibrator — course content auditing tool.

Usage:
  python canvas_calibrator/run_calibration.py \\
    --course-id 4031 \\
    --export-dir export/data/cloud/4031 \\
    --output-dir canvas_calibrator/reports/

Options:
  --skip-export     Skip New Quizzes QTI export (use existing zips in quizzes_qti/)
  --skip-fetch      Skip external URL fetching
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

# Load .env.local for API keys
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
    p.add_argument("--course-id", required=True, help="Canvas course ID")
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
    p.add_argument(
        "--skip-export",
        action="store_true",
        help="Skip New Quizzes QTI export; use existing zips in quizzes_qti/",
    )
    p.add_argument("--skip-fetch", action="store_true", help="Skip external URL fetching")
    p.add_argument("--no-pdfs", action="store_true", help="Skip PDF ingestion")
    p.add_argument("--rebuild-index", action="store_true", help="Force re-embed even if cache exists")
    p.add_argument("--dry-run", action="store_true", help="Parse and index only, no API calls")
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args()

    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")

    log = logging.getLogger("calibrator")
    qti_dir = args.export_dir / "quizzes_qti"

    # --- Step 1: Export New Quizzes QTI zips (unless skipped) ---
    if not args.skip_export:
        print(f"[1/5] Exporting New Quizzes QTI zips for course {args.course_id}…")
        from utils.api import target_api
        if target_api is None:
            p.error("CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN must be set for quiz export")
        from canvas_calibrator.exporters.new_quizzes_exporter import export_new_quizzes
        zips = export_new_quizzes(
            course_id=int(args.course_id),
            export_dir=args.export_dir,
            api=target_api,
            output_dir=qti_dir,
        )
        print(f"      → {len(zips)} zips exported to {qti_dir}")
    else:
        print(f"[1/5] Skipping export (--skip-export)")

    # Collect all zips to process
    zip_files = sorted(qti_dir.glob("*.zip")) if qti_dir.exists() else []
    if not zip_files:
        print(f"ERROR: No zip files found in {qti_dir}. Run without --skip-export first.")
        return 1
    print(f"      → {len(zip_files)} zip(s) to process")

    # --- Step 2: Parse all QTI zips ---
    print(f"[2/5] Parsing {len(zip_files)} QTI zip(s)…")
    from canvas_calibrator.parsers.qti_parser import parse_qti_zip
    all_questions: list[dict] = []
    quiz_titles: list[str] = []
    for zp in zip_files:
        try:
            qs = parse_qti_zip(zp)
            all_questions.extend(qs)
            title = qs[0]["quiz_title"] if qs else zp.stem
            quiz_titles.append(title)
            print(f"      {zp.name}: {len(qs)} questions  ({title})")
        except Exception as e:
            log.error("Failed to parse %s: %s", zp.name, e)
    print(f"      → {len(all_questions)} total questions across {len(quiz_titles)} quizzes")

    if not all_questions:
        print("ERROR: No questions parsed. Aborting.")
        return 1

    # --- Step 3: Load course content ---
    print(f"[3/5] Loading course content from: {args.export_dir}")
    from canvas_calibrator.ingest.content_loader import load_course_content
    docs = load_course_content(
        args.export_dir,
        skip_fetch=args.skip_fetch,
        no_pdfs=args.no_pdfs,
    )
    print(f"      → {len(docs)} documents loaded")

    # --- Step 4: Chunk + Embed ---
    print(f"[4/5] Chunking and embedding documents…")
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

    from canvas_calibrator.rag.retriever import Retriever
    retriever = Retriever(embeddings, indexed_chunks)

    if args.dry_run:
        print("[5/5] DRY RUN — skipping Claude API calls")
    else:
        print(f"[5/5] Running learner agent ({len(all_questions)} questions across {len(quiz_titles)} quizzes)…")

    # --- Step 5: Run learner agent ---
    from canvas_calibrator.agent.learner import run_learner
    results = run_learner(all_questions, retriever, dry_run=args.dry_run)

    correct = sum(1 for r in results if r.verdict == "correct")
    wrong = sum(1 for r in results if r.verdict == "wrong")
    unsupported = sum(1 for r in results if r.verdict == "unsupported")
    total = len(results)
    print(f"      → {correct}/{total} correct  |  {wrong} wrong  |  {unsupported} unsupported")

    # Load course code from exported metadata (best-effort)
    import json
    course_code = str(args.course_id)
    meta_file = args.export_dir / "course" / "course_metadata.json"
    if meta_file.exists():
        try:
            course_code = json.loads(meta_file.read_text(encoding="utf-8")).get(
                "course_code", course_code
            ) or course_code
        except Exception:
            pass

    # --- Step 6: Generate report ---
    print(f"[6/6] Generating report in: {args.output_dir}")
    report_title = f"{len(quiz_titles)} quiz(zes)"
    from canvas_calibrator.report.generator import generate_report
    md_path, html_path = generate_report(
        results,
        course_id=args.course_id,
        course_code=course_code,
        quiz_title=report_title,
        output_dir=args.output_dir,
    )
    print(f"      → {md_path}")
    print(f"      → {html_path}")
    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
