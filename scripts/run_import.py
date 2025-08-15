#!/usr/bin/env python3
"""
scripts/run_import.py

Orchestrates the import pipeline in the right order, using your CanvasAPI client
(from utils.api) and a persistent id_map.json. Supports optional Blueprint sync.
Lazy-imports heavy modules so --dry-run does not require API creds or importers.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Any


ALL_STEPS = ["pages", "assignments", "quizzes", "files", "discussions", "modules", "course"]


def _scan_export(export_root: Path) -> Dict[str, int]:
    """
    Return counts of artifacts discovered in export_root for a dry-run plan.
    """
    counts: Dict[str, int] = {k: 0 for k in ALL_STEPS}
    # pages
    counts["pages"] = len(list((export_root / "pages").rglob("page_metadata.json")))
    # assignments
    counts["assignments"] = len(list((export_root / "assignments").rglob("assignment_metadata.json")))
    # quizzes
    counts["quizzes"] = len(list((export_root / "quizzes").rglob("quiz_metadata.json")))
    # files (sidecar metadata)
    counts["files"] = len(list((export_root / "files").rglob("*.metadata.json")))
    # discussions
    counts["discussions"] = len(list((export_root / "discussions").rglob("discussion_metadata.json")))
    # modules
    mod_file = export_root / "modules" / "modules.json"
    if mod_file.exists():
        try:
            data = json.loads(mod_file.read_text(encoding="utf-8"))
            counts["modules"] = len(data) if isinstance(data, list) else 0
        except Exception:
            counts["modules"] = 0
    # course
    if (export_root / "course" / "course_metadata.json").exists() or (export_root / "course" / "settings.json").exists():
        counts["course"] = 1
    return counts


def _int_keys(d: Dict[Any, Any]) -> Dict[Any, Any]:
    out = {}
    for k, v in (d or {}).items():
        try:
            out[int(k)] = v
        except (ValueError, TypeError):
            out[k] = v
    return out


def _normalize_id_map(m: Dict[str, Dict[Any, Any]]) -> Dict[str, Dict[Any, Any]]:
    int_maps = {"assignments", "files", "quizzes", "discussions", "pages", "modules"}
    norm = {}
    for k, v in (m or {}).items():
        if k in int_maps and isinstance(v, dict):
            norm[k] = _int_keys(v)
        else:
            norm[k] = v
    return norm


def load_id_map(path: Path) -> Dict[str, Dict[Any, Any]]:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return _normalize_id_map(data)
    return {}


def save_id_map(path: Path, id_map: Dict[str, Dict[Any, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(id_map, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run Canvas import pipeline")
    p.add_argument("--export-root", required=True, type=Path,
                   help="Path like export/data/{source_course_id}")
    p.add_argument("--target-course-id", required=True, type=int,
                   help="Target Canvas course ID to import into")
    p.add_argument("--id-map", type=Path,
                   help="Path to id_map.json (default: {export_root}/id_map.json)")
    p.add_argument("--steps", type=str, default=",".join(ALL_STEPS),
                   help=f"Comma-separated steps to run (default: {','.join(ALL_STEPS)})")
    p.add_argument("--include-quiz-questions", action="store_true",
                   help="Also create quiz questions when quizzes data is present")
    p.add_argument("--blueprint-sync", action="store_true",
                   help="Queue a blueprint sync after course settings update")
    p.add_argument("--dry-run", action="store_true",
                   help="Scan export and print what would be imported without making API calls")
    p.add_argument("-v", "--verbose", action="count", default=1,
                   help="Increase verbosity")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    steps = [s.strip() for s in args.steps.split(",") if s.strip()]

    # DRY-RUN early path: no heavy imports or env needed
    if args.dry_run:
        counts = _scan_export(args.export_root)
        print(f"DRY-RUN: plan for steps={steps}")
        for s in steps:
            c = counts.get(s, 0)
            print(f"  - {s:<12} : {c} item(s)")
        # id_map keys present
        id_map_path = args.id_map or (args.export_root / "id_map.json")
        id_map = load_id_map(id_map_path)
        present_maps = sorted(list(id_map.keys()))
        print(f"  id_map keys present: {present_maps if present_maps else 'none'}")
        print("No API calls were made (dry-run).")
        return 0

    # Heavy path: do real imports
    from dotenv import load_dotenv
    load_dotenv()

    from logging_setup import setup_logging, get_logger
    setup_logging(verbosity=args.verbose)
    log = get_logger(artifact="runner", course_id=args.target_course_id)
    log.info("Starting import pipeline steps=%s export_root=%s", args.steps, args.export_root)

    from utils.api import target_api  # type: ignore

    from importers.import_pages import import_pages
    from importers.import_assignments import import_assignments
    from importers.import_quizzes import import_quizzes
    from importers.import_files import import_files
    from importers.import_discussions import import_discussions
    from importers.import_modules import import_modules
    from importers.import_course_settings import import_course_settings

    id_map_path = args.id_map or (args.export_root / "id_map.json")
    id_map: Dict[str, Dict[Any, Any]] = load_id_map(id_map_path)

    for step in steps:
        try:
            if step == "pages":
                import_pages(target_course_id=args.target_course_id,
                             export_root=args.export_root,
                             canvas=target_api,
                             id_map=id_map)
                save_id_map(id_map_path, id_map)

            elif step == "assignments":
                import_assignments(target_course_id=args.target_course_id,
                                   export_root=args.export_root,
                                   canvas=target_api,
                                   id_map=id_map)
                save_id_map(id_map_path, id_map)

            elif step == "quizzes":
                import_quizzes(target_course_id=args.target_course_id,
                               export_root=args.export_root,
                               canvas=target_api,
                               id_map=id_map,
                               include_questions=args.include_quiz_questions)
                save_id_map(id_map_path, id_map)

            elif step == "files":
                import_files(target_course_id=args.target_course_id,
                             export_root=args.export_root,
                             canvas=target_api,
                             id_map=id_map)
                save_id_map(id_map_path, id_map)

            elif step == "discussions":
                import_discussions(target_course_id=args.target_course_id,
                                   export_root=args.export_root,
                                   canvas=target_api,
                                   id_map=id_map)
                save_id_map(id_map_path, id_map)

            elif step == "modules":
                import_modules(target_course_id=args.target_course_id,
                               export_root=args.export_root,
                               canvas=target_api,
                               id_map=id_map)
                save_id_map(id_map_path, id_map)

            elif step == "course":
                import_course_settings(target_course_id=args.target_course_id,
                                       export_root=args.export_root,
                                       canvas=target_api,
                                       queue_blueprint_sync=bool(args.blueprint_sync))
            else:
                log.warning("Unknown step '%s' — skipping", step)
        except Exception as e:
            log.exception("Step '%s' failed: %s", step, e)

    log.info("Import pipeline complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
