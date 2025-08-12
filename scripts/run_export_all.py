# scripts/run_export_all.py
from __future__ import annotations
from pathlib import Path
import argparse

from logging_setup import setup_logging
from utils.api import source_api
from export.export_settings import export_course_settings
from export.export_blueprint_settings import export_blueprint_settings
from export.export_pages import export_pages
from export.export_assignments import export_assignments
from export.export_quizzes import export_quizzes
from export.export_files import export_files
from export.export_discussions import export_discussions
from export.export_modules import export_modules


def export_course_all(course_id: int, export_root: Path, include_questions: bool, verbosity: int) -> None:
    setup_logging(verbosity=verbosity)

    # 1) Settings + course info
    info = export_course_settings(course_id, export_root, source_api)

    # 2) Content
    export_pages(course_id, export_root, source_api)
    export_assignments(course_id, export_root, source_api)
    export_quizzes(course_id, export_root, source_api, include_questions=include_questions)
    export_files(course_id, export_root, source_api)
    export_discussions(course_id, export_root, source_api)

    # 3) Modules (backfill across all artifacts)
    export_modules(course_id, export_root, source_api)

    # 4) Blueprint (if applicable)
    if info.get("is_blueprint"):
        export_blueprint_settings(course_id, export_root, source_api)


def main() -> None:
    p = argparse.ArgumentParser(
        prog="run_export_all",
        description="Export a Canvas course (settings, content, modules, blueprint) deterministically."
    )
    p.add_argument("--course", "-c", type=int, required=True, help="Canvas course ID")
    p.add_argument("--export-root", "-o", type=Path, default=Path("export/data"), help="Output root directory")
    p.add_argument("--questions", action="store_true", help="Include quiz questions (questions.json)")
    p.add_argument("--verbosity", "-v", type=int, default=1, choices=[0,1,2], help="0=WARNING, 1=INFO, 2=DEBUG")

    # Optional slice controls (run a subset). If any are specified, we run only those.
    p.add_argument("--only-settings", action="store_true")
    p.add_argument("--only-pages", action="store_true")
    p.add_argument("--only-assignments", action="store_true")
    p.add_argument("--only-quizzes", action="store_true")
    p.add_argument("--only-files", action="store_true")
    p.add_argument("--only-discussions", action="store_true")
    p.add_argument("--only-modules", action="store_true")
    p.add_argument("--only-blueprint", action="store_true")

    args = p.parse_args()

    setup_logging(verbosity=args.verbosity)

    export_root: Path = args.export_root
    cid: int = args.course

    # If any --only-* flags are set, run exactly those; otherwise run the full pipeline.
    only_flags = {
        "settings": args.only_settings,
        "pages": args.only_pages,
        "assignments": args.only_assignments,
        "quizzes": args.only_quizzes,
        "files": args.only_files,
        "discussions": args.only_discussions,
        "modules": args.only_modules,
        "blueprint": args.only_blueprint,
    }

    if any(only_flags.values()):
        info = {"is_blueprint": False}
        if args.only_settings:
            info = export_course_settings(cid, export_root, source_api)
        if args.only_pages:
            export_pages(cid, export_root, source_api)
        if args.only_assignments:
            export_assignments(cid, export_root, source_api)
        if args.only_quizzes:
            export_quizzes(cid, export_root, source_api, include_questions=args.questions)
        if args.only_files:
            export_files(cid, export_root, source_api)
        if args.only_discussions:
            export_discussions(cid, export_root, source_api)
        if args.only_modules:
            export_modules(cid, export_root, source_api)
        if args.only_blueprint:
            # If you ran only settings earlier, we have a real flag; otherwise re-check settings:
            if not any([args.only_settings]):
                info = export_course_settings(cid, export_root, source_api)
            if info.get("is_blueprint"):
                export_blueprint_settings(cid, export_root, source_api)
        return

    # Full pipeline
    export_course_all(cid, export_root, include_questions=args.questions, verbosity=args.verbosity)


if __name__ == "__main__":
    main()

#### course_id = 76739  # https://canvas.sfu.ca/courses/76739 (CRM110)

