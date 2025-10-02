"""CLI entry-point to rewrite exported HTML using import id_map mappings."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from importers.import_course import load_id_map
from utils.html_postprocessor import MissingSourceCourseIdError, postprocess_html


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rewrite Canvas links in exported HTML using id_map.json")
    parser.add_argument("export_root", type=Path, help="Path to the export root directory")
    parser.add_argument("--target-course-id", type=int, required=True, help="Canvas course id for the imported course")
    parser.add_argument(
        "--source-course-id",
        type=int,
        help="Optional override for the source Canvas course id (auto-detected if omitted)",
    )
    parser.add_argument(
        "--id-map",
        type=Path,
        help="Path to id_map.json (defaults to <export_root>/id_map.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report files that would be rewritten without modifying them",
    )
    parser.add_argument(
        "--extra-html",
        type=Path,
        action="append",
        default=[],
        help="Additional HTML file paths to include in processing",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    export_root: Path = args.export_root.expanduser().resolve()
    if not export_root.exists() or not export_root.is_dir():
        parser.error(f"export_root {export_root} is not a directory")

    id_map_path = args.id_map or (export_root / "id_map.json")
    if not id_map_path.exists():
        parser.error(f"id_map not found at {id_map_path}; run the importer first or pass --id-map")

    id_map = load_id_map(id_map_path)

    extra_paths = [p.expanduser().resolve() for p in args.extra_html]

    try:
        report = postprocess_html(
            export_root=export_root,
            target_course_id=args.target_course_id,
            id_map=id_map,
            source_course_id=args.source_course_id,
            dry_run=args.dry_run,
            extra_paths=extra_paths,
        )
    except MissingSourceCourseIdError as exc:
        parser.error(str(exc))

    for path in report.rewritten_files:
        print(f"updated {path}")

    if args.dry_run:
        print(f"dry-run complete: {report.rewrites_applied} of {report.total_files} files would change")
    else:
        print(f"rewrote {report.rewrites_applied} of {report.total_files} HTML files")

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
