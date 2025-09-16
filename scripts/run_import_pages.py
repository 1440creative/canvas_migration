#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import argparse
from dotenv import load_dotenv

from logging_setup import setup_logging, get_logger
from utils.api import target_api
from importers.import_pages import import_pages
from run_import import load_id_map, save_id_map  # reuse helpers

def parse_args():
    p = argparse.ArgumentParser(description="Import only Pages into a target Canvas course")
    p.add_argument("--export-root", required=True, type=Path, help="Path like export/data/{source_course_id}")
    p.add_argument("--target-course-id", required=True, type=int, help="Target Canvas course ID")
    p.add_argument("--id-map", type=Path, help="Path to id_map.json (default: {export_root}/id_map.json)")
    p.add_argument("-v", "--verbose", action="count", default=1)
    return p.parse_args()

def main() -> int:
    load_dotenv()
    args = parse_args()
    setup_logging(verbosity=args.verbose)
    log = get_logger(artifact="pages", course_id=args.target_course_id)

    if target_api is None:
        log.error("target_api not configured. Set CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN in .env")
        return 2

    id_map_path = args.id_map or (args.export_root / "id_map.json")
    id_map = load_id_map(id_map_path)

    log.info("Starting pages import export_root=%s", args.export_root)
    counters = import_pages(
        target_course_id=args.target_course_id,
        export_root=args.export_root,
        canvas=target_api,
        id_map=id_map,
    )
    save_id_map(id_map_path, id_map)
    log.info("Done: %s", counters)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
