#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# --- ensure repo root on sys.path ---
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from importers.import_course import (
    import_course,
    scan_export,
    ALL_STEPS,
    load_id_map,
    save_id_map,
)
from logging_setup import setup_logging


def _derive_course_seed(export_root: Path) -> Dict[str, str]:
    seed: Dict[str, str] = {}
    meta_path = export_root / "course" / "course_metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(meta, dict):
                name = meta.get("name") or meta.get("course_code")
                code = meta.get("course_code") or meta.get("course_code_display")
                if isinstance(name, str) and name.strip():
                    seed["name"] = name.strip()
                if isinstance(code, str) and code.strip():
                    seed["course_code"] = code.strip()
        except Exception:
            pass

    fallback_name = seed.get("name") or export_root.name
    seed.setdefault("name", fallback_name)
    seed.setdefault("course_code", seed["name"])
    return seed


def _create_target_course(canvas, *, account_id: int, export_root: Path) -> int:
    seed = _derive_course_seed(export_root)
    payload = {"course": {"name": seed["name"], "course_code": seed["course_code"]}}
    resp = canvas.post(f"/api/v1/accounts/{account_id}/courses", json=payload)

    try:
        body = resp.json()
    except Exception:
        body = {}

    new_id: Optional[int] = None
    if isinstance(body, dict):
        candidate = body.get("id")
        if candidate is None and isinstance(body.get("course"), dict):
            candidate = body["course"].get("id")
        if candidate is not None:
            try:
                new_id = int(candidate)
            except (TypeError, ValueError):
                new_id = None

    if new_id is None:
        raise RuntimeError("Canvas did not return a new course id")

    return new_id


def _parse_steps(s: Optional[str]) -> List[str]:
    if not s:
        return list(ALL_STEPS)
    raw = [p.strip() for p in s.split(",")]
    steps = [p for p in raw if p]
    # keep only known steps, preserve order, de-dup
    seen = set()
    ordered: List[str] = []
    for st in steps:
        if st in ALL_STEPS and st not in seen:
            ordered.append(st)
            seen.add(st)
    return ordered or list(ALL_STEPS)


def _print_dry_run(export_root: Path, steps: List[str]) -> None:
    counts = scan_export(export_root)
    print("DRY-RUN: plan for steps")
    for st in steps:
        n = counts.get(st, 0)
        print(f" - {st}: {n} item(s)")
    # Dry-run uses an empty in-memory id_map
    print("id_map keys present: none")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run Canvas import pipeline.")
    ap.add_argument("--export-root", required=True, type=Path, help="Path to export/data/<SOURCE_ID>")
    ap.add_argument("--target-course-id", type=int, help="Target Canvas course ID (required unless --dry-run)")
    ap.add_argument("--steps", default=None, help=f"Comma-separated steps subset. Known: {','.join(ALL_STEPS)}")
    ap.add_argument("--resume", action="store_true",
                    help="Resume using existing id_map.json in export-root (if present).")
    ap.add_argument("--id-map", type=Path, default=None,
                    help="Override path to id_map.json (default: <export-root>/id_map.json)")
    ap.add_argument(
        "--include-quiz-questions",
        dest="include_quiz_questions",
        action="store_true",
        default=True,
        help="Also import quiz questions (default: enabled).",
    )
    ap.add_argument(
        "--skip-quiz-questions",
        dest="include_quiz_questions",
        action="store_false",
        help="Skip importing quiz questions even if questions.json is present.",
    )
    ap.add_argument("--term-name", default="Default",
                    help="Enrollment term name to assign in the target course (default: 'Default'). Use empty string to skip.")
    ap.add_argument("--term-id", type=int, default=None,
                    help="Explicit enrollment term ID to assign (overrides --term-name lookup).")
    ap.add_argument("--no-auto-term", action="store_true",
                    help="Disable automatic enrollment term reassignment.")
    ap.add_argument("--no-course-dates", action="store_true",
                    help="Do not force participation to 'Course' (restrict_enrollments_to_course_dates=false).")
    ap.add_argument(
        "--target-account-id",
        type=int,
        default=None,
        help="Override the Canvas account id to use for term lookups and settings updates.",
    )
    ap.add_argument("--sis-course-id", default=None,
                    help="Set the SIS course ID in the target Canvas (default: blank).")
    ap.add_argument("--integration-id", default=None,
                    help="Set the integration_id in the target Canvas (default: blank).")
    ap.add_argument("--sis-import-id", default=None,
                    help="Set the sis_import_id in the target Canvas (default: blank).")
    ap.add_argument("--dry-run", action="store_true", help="Plan counts only; no API calls.")
    ap.add_argument("--summary-json", type=Path, default=None,
                    help="If provided, write a JSON summary of the run here.")
    ap.add_argument("-v", "--verbose", action="count", default=0)

    args = ap.parse_args(argv)

    setup_logging(verbosity=args.verbose or 1)

    export_root: Path = args.export_root
    steps = _parse_steps(args.steps)
    id_map_path = args.id_map or (export_root / "id_map.json")

    # Lazy import here to avoid importing requests-heavy modules in dry-run
    from utils.api import CanvasAPI

    # Light logging; importers use structured logging already
    if args.verbose >= 2:
        os.environ.setdefault("PYTHONWARNINGS", "default")

    if args.dry_run:
        _print_dry_run(export_root, steps)
        return 0

    if args.target_course_id is None and args.target_account_id is None:
        ap.error("Provide --target-course-id or supply --target-account-id to create a new course.")

    target_course_id: Optional[int] = args.target_course_id

    # Build a minimal API client for "programmatic import"
    base = os.getenv("CANVAS_TARGET_URL")
    token = os.getenv("CANVAS_TARGET_TOKEN")
    if not base or not token:
        print("ERROR: CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN must be set in environment/.env", file=sys.stderr)
        return 2

    canvas = CanvasAPI(base, token)

    created_course_id: Optional[int] = None
    if target_course_id is None:
        try:
            target_course_id = _create_target_course(
                canvas,
                account_id=int(args.target_account_id),
                export_root=export_root,
            )
            created_course_id = target_course_id
            print(f"Created new Canvas course {target_course_id} under account {args.target_account_id}")
        except Exception as exc:
            print(f"ERROR: failed to create course under account {args.target_account_id}: {exc}", file=sys.stderr)
            return 3

    assert target_course_id is not None

    # If resuming, load existing id_map; else start from scratch
    if args.resume and id_map_path.exists():
        id_map = load_id_map(id_map_path)
    else:
        id_map = {}

    result = import_course(
        target_course_id=target_course_id,
        export_root=export_root,
        canvas=canvas,
        steps=steps,
        id_map_path=id_map_path,
        include_quiz_questions=args.include_quiz_questions,
        continue_on_error=True,
        auto_term_name=None if args.no_auto_term or not args.term_name else args.term_name,
        auto_term_id=args.term_id,
        force_course_dates=not args.no_course_dates,
        sis_course_id=args.sis_course_id,
        integration_id=args.integration_id,
        sis_import_id=args.sis_import_id,
        target_account_id=args.target_account_id,
    )

    # Persist id_map after a real run (import_course already saves step-by-step,
    # but we ensure it here in case a caller passed a custom path).
    try:
        save_id_map(id_map_path, load_id_map(id_map_path))
    except Exception:
        # Don't fail the run just because save is flaky on some FS
        pass

    # Optional summary artifact
    if args.summary_json:
        summary = {
            "target_course_id": target_course_id,
            "export_root": str(export_root),
            "steps": steps,
            "counts": result.get("counts", {}),
            "errors": result.get("errors", []),
            "target_account_id": args.target_account_id,
            "created_course_id": created_course_id,
            "id_map_keys": sorted(load_id_map(id_map_path).keys()) if id_map_path.exists() else [],
        }
        summary_path = args.summary_json
        if summary_path.exists() and summary_path.is_dir():
            summary_path = summary_path / "import_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote summary → {summary_path}")

    print("Import finished.")
    if result.get("errors"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
