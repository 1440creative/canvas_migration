#!/usr/bin/env python3
"""
Canvas import runner.

Examples:
  python scripts/run_import.py --export-root export/data --target-course-id 999 --dry-run -v
  python scripts/run_import.py --export-root export/data --target-course-id 999 -vv
  python scripts/run_import.py --export-root export/data --create-in-account 135 --course-name "CMPT 101" --publish-new-course

Notes:
- You must have CANVAS_SOURCE_URL/TOKEN and CANVAS_TARGET_URL/TOKEN configured for utils.api.
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# --- ensure repo root on sys.path ---
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from logging_setup import setup_logging, get_logger
from utils.api import source_api, target_api  # source = read from, target = write to
from importers.import_course import import_course, ALL_STEPS as IMPORT_STEPS


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _create_target_course(
    *,
    account_id: int,
    export_root: Path,
    source_course_id: int,
    name: str | None,
    code: str | None,
    term_id: int | None,
    publish: bool,
    log,
) -> int:
    """
    Create a new course on the TARGET Canvas under the given subaccount,
    returning the new course id.
    """
    # Prefer metadata defaults if not given
    meta_path = export_root / str(source_course_id) / "course" / "course_metadata.json"
    exported_meta = _read_json(meta_path)
    course_name = name or exported_meta.get("name") or "Imported Course"
    course_code = code or exported_meta.get("course_code") or course_name.replace(" ", "-")[:50]

    payload: dict = {"course": {"name": course_name, "course_code": course_code}}
    if term_id:
        payload["course"]["term_id"] = int(term_id)
    if publish:
        payload["course"]["workflow_state"] = "available"

    log.info(
        "Creating target course",
        extra={"account_id": account_id, "name": course_name, "course_code": course_code},
    )
    resp = target_api.post(f"/api/v1/accounts/{account_id}/courses", json=payload)

    # Try to extract id from body first
    try:
        body = resp.json()
    except Exception:
        body = {}
    new_id = body.get("id")

    # Some Canvas deployments return 201 + Location without id in body
    if not isinstance(new_id, int) and "Location" in resp.headers:
        follow = target_api.session.get(resp.headers["Location"])
        follow.raise_for_status()
        try:
            body = follow.json()
        except Exception:
            body = {}
        new_id = body.get("id")

    if not isinstance(new_id, int):
        raise RuntimeError("Failed to create target course (no id returned)")

    log.info("Created target course", extra={"new_course_id": new_id})
    return int(new_id)


def main() -> int:
    p = argparse.ArgumentParser(description="Run Canvas course import (programmatic).")
    p.add_argument("--export-root", type=Path, required=True, help="Root directory of export data (e.g., export/data)")
    # Destination selection: either provide an existing target course id, or request a new one in an account
    dest = p.add_mutually_exclusive_group(required=True)
    dest.add_argument("--target-course-id", type=int, help="Existing target Canvas course id to import INTO")
    dest.add_argument(
        "--create-in-account",
        type=int,
        metavar="ACCOUNT_ID",
        help="Create a NEW target course in this subaccount id on the target instance and import into it",
    )
    # New-course options (used only with --create-in-account)
    p.add_argument("--course-name", help="Name for the NEW course (default: from exported course metadata)")
    p.add_argument("--course-code", help="Course code for the NEW course (default: derived from name)")
    p.add_argument("--term-id", type=int, help="Enrollment term id for the NEW course (optional)")
    p.add_argument("--publish-new-course", action="store_true", help="Publish the NEW course upon creation")

    # Import steps & behavior
    p.add_argument(
        "--steps",
        nargs="+",
        choices=IMPORT_STEPS,
        default=IMPORT_STEPS,
        help="Subset of import steps to run (default: all)",
    )
    p.add_argument(
        "--include-quiz-questions",
        action="store_true",
        help="When importing quizzes, also import questions (if present in export)",
    )
    p.add_argument(
        "--queue-blueprint-sync",
        action="store_true",
        help="Queue a Blueprint sync after course settings (if blueprint metadata present)",
    )
    p.add_argument("--continue-on-error", action="store_true", help="Continue other steps if one fails")
    p.add_argument("--dry-run", action="store_true", help="Print planned steps and exit without importing")
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v=INFO, -vv=DEBUG)")
    args = p.parse_args()

    # Setup logging (0=WARNING, 1=INFO, 2+=DEBUG)
    verbosity = 1 if args.verbose == 1 else (2 if args.verbose >= 2 else 0)
    setup_logging(verbosity=verbosity)
    # Use source course id (from export tree) purely for logging context
    # If you exported from course X, the export lives under export_root/X/...
    # We may import into a different/new target course id.
    # For context, try to infer the source course id directory under export_root.
    # If ambiguous, fall back to '-'.
    try:
        # Heuristic: if only one directory under export_root, use it
        subdirs = [d.name for d in args.export_root.iterdir() if d.is_dir()]
        src_id_for_log = int(subdirs[0]) if len(subdirs) == 1 and subdirs[0].isdigit() else "-"
    except Exception:
        src_id_for_log = "-"
    log = get_logger(artifact="runner", course_id=src_id_for_log)

    # Dry-run: print the planned steps (tests look for " - <step>" lines)
    if args.dry_run:
        print("Import plan:")
        for s in args.steps:
            print(f" - {s}")
        return 0

    # Determine target course id (existing vs create-new)
    if args.create_in_account:
        target_course_id = _create_target_course(
            account_id=args.create_in_account,
            export_root=args.export_root,
            source_course_id=int(src_id_for_log) if isinstance(src_id_for_log, int) else 0,
            name=args.course_name,
            code=args.course_code,
            term_id=args.term_id,
            publish=args.publish_new_course,
            log=log,
        )
    else:
        target_course_id = int(args.target_course_id)

    # Kick off the programmatic import
    log.info(
        "Starting import",
        extra={
            "export_root": str(args.export_root),
            "target_course_id": target_course_id,
            "steps": ",".join(args.steps),
        },
    )

    result = import_course(
        target_course_id=target_course_id,
        export_root=args.export_root,
        canvas=target_api,  # write into TARGET instance
        steps=args.steps,
        id_map_path=args.export_root / str(src_id_for_log) / "id_map.json" if isinstance(src_id_for_log, int) else None,
        include_quiz_questions=args.include_quiz_questions,
        queue_blueprint_sync=args.queue_blueprint_sync,
        continue_on_error=args.continue_on_error,
    )

    # Summarize + exit code
    counts = result.get("counts", {})
    errors = result.get("errors", [])
    log.info("Import complete", extra={"counts": counts, "errors": len(errors), "target_course_id": target_course_id})
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
