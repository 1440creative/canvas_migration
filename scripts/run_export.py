
#!/usr/bin/env python3
"""Minimal Canvas export runner

Usage:
  python scripts/run_export.py --course-id 12345 --export-root export/data -v --include-questions --steps pages files modules
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

# --- ensure repo root is on sys.path when running as a script from scripts/ ---
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.api import source_api  # now resolves
from export.export_pages import export_pages
from export.export_modules import export_modules
from export.export_assignments import export_assignments
from export.export_quizzes import export_quizzes
from export.export_discussions import export_discussions
from export.export_files import export_files
from export.export_settings import export_course_settings
from export.export_blueprint_settings import export_blueprint_settings

ALL_STEPS = ["pages", "assignments", "quizzes", "files", "discussions", "modules", "course"]

def main() -> int:
    p = argparse.ArgumentParser(description="Run Canvas course export")
    p.add_argument("--course-id", type=int, required=True, help="Canvas course id to export")
    p.add_argument("--export-root", type=Path, required=True, help="Root directory for export data (e.g., export/data)")
    p.add_argument("--steps", nargs="+", choices=ALL_STEPS, default=ALL_STEPS, help="Subset of steps to run (default: all)")
    p.add_argument("--include-questions", action="store_true", help="Include quiz questions.json")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging to stdout")
    p.add_argument("--continue-on-error", action="store_true", help="Continue other steps if one fails")
    args = p.parse_args()

    cid = args.course_id
    root = args.export_root

    if args.verbose:
        print(f"Exporting course {cid} -> {root}/{cid}")
        print(f"Steps: {args.steps}  include_questions={args.include_questions}")

    counts = {}
    errors = []

    def run_step(name: str):
        try:
            if name == "pages":
                metas = export_pages(cid, root, source_api)  # List[dict]
                counts[name] = len(metas)
            elif name == "assignments":
                metas = export_assignments(cid, root, source_api)
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
            elif name == "modules":
                metas = export_modules(cid, root, source_api)
                counts[name] = len(metas)
            elif name == "course":
                meta = export_course_settings(cid, root, source_api)
                # also try blueprint info (best-effort)
                bp = export_blueprint_settings(cid, root, source_api)
                counts[name] = 1  # single settings blob
            else:
                raise ValueError(f"unknown step: {name}")
            if args.verbose:
                print(f"✓ {name:12s}: {counts[name]} item(s)")
        except Exception as e:
            errors.append((name, e))
            if args.verbose:
                print(f"✗ {name:12s}: {type(e).__name__}: {e}")
            if not args.continue_on_error:
                raise

    for step in args.steps:
        run_step(step)

    if args.verbose:
        print("\nSummary:")
        for s in ALL_STEPS:
            if s in counts:
                print(f"  - {s:12s}: {counts[s]} item(s)")
        if errors:
            print("\nErrors:")
            for s, e in errors:
                print(f"  - {s}: {type(e).__name__}: {e}")

    return 0 if not errors else 2

if __name__ == "__main__":
    raise SystemExit(main())
