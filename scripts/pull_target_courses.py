#!/usr/bin/env python3
"""
Pull all courses from the TARGET Canvas server to local disk.

Lists every course in account 110 (root) via the target API, then exports
each one using the same pipeline as run_export.py.

Usage:
  python scripts/pull_target_courses.py --export-root export/data
  python scripts/pull_target_courses.py --export-root export/data --dry-run
  python scripts/pull_target_courses.py --export-root export/data --steps pages modules
  python scripts/pull_target_courses.py --export-root export/data --account-id 110 --limit 10
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(str(REPO_ROOT / ".env"))
    load_dotenv(str(REPO_ROOT / ".env.local"), override=True)
except ImportError:
    pass

import importlib.util as _ilu

from utils.api import CanvasAPI, target_api

def _import_make_manifest():
    spec = _ilu.spec_from_file_location(
        "make_course_manifest",
        REPO_ROOT / "scripts" / "make_course_manifest.py",
    )
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

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

DEFAULT_ACCOUNT_ID = 110


def list_courses(api: CanvasAPI, account_id: int) -> list[dict]:
    print(f"Fetching course list from account {account_id}...")
    courses = api.get(f"/accounts/{account_id}/courses", params={"per_page": 100})
    if not isinstance(courses, list):
        raise RuntimeError(f"Unexpected response from /accounts/{account_id}/courses: {courses!r}")
    return courses


def run_export(course_id: int, export_root: Path, steps: list[str], dry_run: bool) -> None:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_export.py"),
        "--course-id", str(course_id),
        "--export-root", str(export_root),
        "--server", "target",
    ]
    if steps:
        cmd += ["--steps", *steps]

    if dry_run:
        print(f"  [dry-run] {' '.join(cmd)}")
        return

    result = subprocess.run(cmd)
    if result.returncode not in (0, 2):  # 2 = partial errors (continue-on-error)
        raise subprocess.CalledProcessError(result.returncode, cmd)


def main() -> int:
    p = argparse.ArgumentParser(description="Export all TARGET courses to local disk")
    p.add_argument("--export-root", type=Path, default=Path("export/data/target_dump"),
                   help="Root directory for exported course data (default: export/data/target_dump)")
    p.add_argument("--account-id", type=int, default=DEFAULT_ACCOUNT_ID,
                   help=f"Canvas account ID to list courses from (default: {DEFAULT_ACCOUNT_ID})")
    p.add_argument("--steps", nargs="+", choices=ALL_STEPS,
                   help="Subset of export steps to run (default: all)")
    p.add_argument("--limit", type=int, default=None,
                   help="Only export the first N courses")
    p.add_argument("--dry-run", action="store_true",
                   help="Print commands without running them")
    p.add_argument("--skip-ids", nargs="+", type=int, default=[],
                   help="Course IDs to skip")
    p.add_argument("--skip-manifest", action="store_true",
                   help="Do not generate a manifest.xlsx after each export")
    args = p.parse_args()

    if target_api is None:
        p.error("CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN must be set in .env or .env.local")

    courses = list_courses(target_api, args.account_id)

    skip = set(args.skip_ids)
    courses = [c for c in courses if c.get("id") not in skip]

    if args.limit is not None:
        courses = courses[: args.limit]

    print(f"Found {len(courses)} courses to export.\n")

    make_manifest = None
    if not args.skip_manifest:
        make_manifest = _import_make_manifest().build_manifest

    failed: list[int] = []
    for i, course in enumerate(courses, 1):
        cid = course["id"]
        name = course.get("name", "(no name)")
        print(f"[{i}/{len(courses)}] Course {cid}: {name}")
        try:
            run_export(cid, args.export_root, args.steps or [], args.dry_run)
            if make_manifest and not args.dry_run:
                course_dir = args.export_root / str(cid)
                make_manifest(course_dir, course_dir / "manifest.xlsx")
        except (subprocess.CalledProcessError, Exception) as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            failed.append(cid)

    print(f"\nDone. {len(courses) - len(failed)}/{len(courses)} courses exported successfully.")
    if failed:
        print(f"Failed course IDs: {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
