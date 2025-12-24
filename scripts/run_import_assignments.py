#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse
from dotenv import load_dotenv

from logging_setup import setup_logging, get_logger
from utils.api import target_api
from importers.import_assignments import import_assignments
from run_import import load_id_map, save_id_map

def parse_args():
    p = argparse.ArgumentParser(description="Import Assignments only")
    p.add_argument("--export-root", required=True, type=Path)
    p.add_argument("--target-course-id", required=True, type=int)
    p.add_argument("--id-map", type=Path)
    p.add_argument("--update-in-place", action="store_true", help="Update existing assignments in place.")
    p.add_argument("-v", "--verbose", action="count", default=1)
    return p.parse_args()

def main() -> int:
    load_dotenv()
    args = parse_args()
    setup_logging(verbosity=args.verbose)
    log = get_logger(artifact="assignments", course_id=args.target_course_id)

    if target_api is None:
        log.error("target_api not configured. Set CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN in .env")
        return 2

    id_map_path = args.id_map or (args.export_root / "id_map.json")
    id_map = load_id_map(id_map_path)

    log.info("Starting assignments import export_root=%s", args.export_root)
    counters = import_assignments(
        target_course_id=args.target_course_id,
        export_root=args.export_root,
        canvas=target_api,
        id_map=id_map,
        update_mode=args.update_in_place,
    )
    save_id_map(id_map_path, id_map)
    log.info("Done: %s", counters)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
