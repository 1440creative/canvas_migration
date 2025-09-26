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
    ap.add_argument("--target-course-id", required=True, type=int, help="Target Canvas course ID")
    ap.add_argument("--steps", default=None, help=f"Comma-separated steps subset. Known: {','.join(ALL_STEPS)}")
    ap.add_argument("--resume", action="store_true",
                    help="Resume using existing id_map.json in export-root (if present).")
    ap.add_argument("--id-map", type=Path, default=None,
                    help="Override path to id_map.json (default: <export-root>/id_map.json)")
    ap.add_argument("--include-quiz-questions", action="store_true", help="Also import quiz questions.")
    ap.add_argument("--dry-run", action="store_true", help="Plan counts only; no API calls.")
    ap.add_argument("--summary-json", type=Path, default=None,
                    help="If provided, write a JSON summary of the run here.")
    ap.add_argument("-v", "--verbose", action="count", default=0)

    args = ap.parse_args(argv)

    export_root: Path = args.export_root
    target_course_id: int = args.target_course_id
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

    # Build a minimal API client for "programmatic import"
    base = os.getenv("CANVAS_TARGET_URL")
    token = os.getenv("CANVAS_TARGET_TOKEN")
    if not base or not token:
        print("ERROR: CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN must be set in environment/.env", file=sys.stderr)
        return 2

    canvas = CanvasAPI(base, token)

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
            "id_map_keys": sorted(load_id_map(id_map_path).keys()) if id_map_path.exists() else [],
        }
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote summary → {args.summary_json}")

    print("Import finished.")
    if result.get("errors"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
