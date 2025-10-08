#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse
from dotenv import load_dotenv

from logging_setup import setup_logging, get_logger
from utils.api import target_api
from importers.import_quizzes import import_quizzes
from run_import import load_id_map, save_id_map

def parse_args():
    p = argparse.ArgumentParser(description="Import Quizzes only")
    p.add_argument("--export-root", required=True, type=Path)
    p.add_argument("--target-course-id", required=True, type=int)
    p.add_argument(
        "--include-questions",
        dest="include_questions",
        action="store_true",
        default=True,
        help="Import quiz questions.json payloads (default: enabled).",
    )
    p.add_argument(
        "--skip-questions",
        dest="include_questions",
        action="store_false",
        help="Skip importing quiz questions.",
    )
    p.add_argument("--id-map", type=Path)
    p.add_argument("-v", "--verbose", action="count", default=1)
    return p.parse_args()

def main() -> int:
    load_dotenv()
    args = parse_args()
    setup_logging(verbosity=args.verbose)
    log = get_logger(artifact="quizzes", course_id=args.target_course_id)

    if target_api is None:
        log.error("target_api not configured. Set CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN in .env")
        return 2

    id_map_path = args.id_map or (args.export_root / "id_map.json")
    id_map = load_id_map(id_map_path)

    log.info("Starting quizzes import export_root=%s", args.export_root)
    counters = import_quizzes(
        target_course_id=args.target_course_id,
        export_root=args.export_root,
        canvas=target_api,
        id_map=id_map,
        include_questions=args.include_questions,
    )
    save_id_map(id_map_path, id_map)
    log.info("Done: %s", counters)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
