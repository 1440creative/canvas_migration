#!/usr/bin/env python3
"""
Canvas export runner (merged version).

Usage:
  python scripts/run_export.py --course-id 12345 --export-root export/data -v
  python scripts/run_export.py --course-id 12345 --steps pages assignments
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

# --- ensure repo root on sys.path ---
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from logging_setup import setup_logging, get_logger
from utils.api import source_api
from export.export_pages import export_pages
from export.export_modules import export_modules
from export.export_assignments import export_assignments
from export.export_assignment_groups import export_assignment_groups
from export.export_quizzes import export_quizzes
from export.export_discussions import export_discussions
from export.export_announcements import export_announcements
from export.export_files import export_files
from export.export_settings import export_course_settings
from export.export_blueprint_settings import export_blueprint_settings
from export.export_home import export_home
from export.export_rubrics import export_rubrics
from export.export_rubric_links import export_rubric_links
from export.export_syllabus import export_syllabus


ALL_STEPS = [
    "pages",
    "assignments",
    "assignment_groups",
    "quizzes",
    "files",
    "discussions",
    "announcements",
    "modules",
    "rubrics",
    "rubric_links",
    "syllabus",
    "course",
]


def main() -> int:
    p = argparse.ArgumentParser(description="Run Canvas course export")
    p.add_argument("--course-id", type=int, required=True, help="Canvas course id to export")
    p.add_argument("--export-root", type=Path, required=True, help="Root directory for export data (e.g., export/data)")
    p.add_argument("--steps", nargs="+", choices=ALL_STEPS, default=ALL_STEPS, help="Subset of steps to run (default: all)")
    p.add_argument(
        "--include-questions",
        dest="include_questions",
        action="store_true",
        default=True,
        help="Include quiz questions.json (default: enabled).",
    )
    p.add_argument(
        "--skip-questions",
        dest="include_questions",
        action="store_false",
        help="Skip exporting quiz questions.json.",
    )
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv)")
    p.add_argument("--continue-on-error", action="store_true", help="Continue other steps if one fails")
    args = p.parse_args()

    # Setup logging (0=WARNING, 1=INFO, 2+=DEBUG)
    verbosity = 0
    if args.verbose == 1:
        verbosity = 1
    elif args.verbose >= 2:
        verbosity = 2
    setup_logging(verbosity=verbosity)
    log = get_logger(artifact="runner", course_id=args.course_id)

    cid = args.course_id
    root = args.export_root

    counts: dict[str, int] = {}
    errors: list[tuple[str, Exception]] = []

    def run_step(name: str) -> None:
        try:
            if name == "pages":
                metas = export_pages(cid, root, source_api)
                counts[name] = len(metas)
            elif name == "assignments":
                metas = export_assignments(cid, root, source_api)
                counts[name] = len(metas)
            elif name == "assignment_groups":
                metas = export_assignment_groups(cid, root, source_api)
                counts[name] = len(metas)
            elif name == "quizzes":
                metas = export_quizzes(cid, root, source_api, include_questions=args.include_questions)
                counts[name] = len(metas)
            elif name == "files":
                metas = export_files(cid, root, source_api)
                counts[name] = len(metas)
            elif name == "discussions":
                metas = export_discussions(cid, root, source_api)
                counts[name] = len(metas)
            elif name == "announcements":
                metas = export_announcements(cid, root, source_api)
                counts[name] = len(metas)
            elif name == "modules":
                metas = export_modules(cid, root, source_api)
                counts[name] = len(metas)
            elif name == "rubrics":
                metas = export_rubrics(cid, root, source_api)
                counts[name] = len(metas)
            elif name == "rubric_links":
                data = export_rubric_links(cid, root, source_api)
                counts[name] = len(data)
            elif name == "syllabus":
                export_syllabus(cid, root, source_api)
                counts[name] = 1
            elif name == "course":
                export_course_settings(cid, root, source_api)
                export_blueprint_settings(cid, root, source_api)
                export_home(cid, root, source_api)
                export_syllabus(cid, root, source_api)
                export_rubrics(cid, root, source_api)
                export_rubric_links(cid, root, source_api)
                export_assignment_groups(cid, root, source_api)
                counts[name] = 1
            else:
                raise ValueError(f"unknown step: {name}")
            log.info("✓ step complete", extra={"step": name, "count": counts[name]})
        except Exception as e:
            errors.append((name, e))
            log.error("✗ step failed", extra={"step": name, "error": str(e)})
            if not args.continue_on_error:
                raise

    for step in args.steps:
        run_step(step)

    log.info("export pipeline complete", extra={"counts": counts, "errors": len(errors)})
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
