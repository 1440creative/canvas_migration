#!/usr/bin/env python3
"""Apply typographic (curly) quotes to Canvas course content on the target server.

Fetches pages, assignments, and discussion prompts for each course and replaces
ASCII straight quotes (" ') with typographic equivalents (" " ' ') in HTML body
text. Attributes and code blocks are never touched. Pages are processed in Canvas
position order.

Usage:
    python scripts/curly_quotes.py --course-ids 101,202,303 --dry-run
    python scripts/curly_quotes.py --course-ids 101 --content-types pages
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path
from typing import List, Optional, Set

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from logging_setup import get_logger, setup_logging
from utils.api import CanvasAPI
from utils.typographic_quotes import fix_quotes

CONTENT_TYPES: Set[str] = {"pages", "assignments", "discussions"}


def _parse_course_ids(raw: str) -> List[int]:
    out: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError as exc:
            raise ValueError(f"Invalid course id: {part!r}") from exc
    return out


def _parse_content_types(raw: str) -> Set[str]:
    items = {item.strip().lower() for item in raw.split(",") if item.strip()}
    invalid = sorted(items - CONTENT_TYPES)
    if invalid:
        raise ValueError(f"Unknown content types: {', '.join(invalid)}. Valid: {', '.join(sorted(CONTENT_TYPES))}")
    return items or set(CONTENT_TYPES)


def _build_summary_lines(summary: dict, *, dry_run: bool) -> List[str]:
    label = "DRY RUN — no changes were written" if dry_run else "Changes written to Canvas"
    col_w = 13
    headers = ["Course ID", "Pages", "Assignments", "Discussions", "Quotes Fixed"]
    widths = [12] + [col_w] * (len(headers) - 1)

    def row(*cells):
        return "  ".join(str(c).ljust(w) for c, w in zip(cells, widths))

    divider = "  ".join("-" * w for w in widths)
    lines = [
        "",
        f"Typographic Quotes — Summary  ({label})",
        divider,
        row(*headers),
        divider,
    ]

    total_quotes = 0
    for course_id, types in summary.items():
        replacements = sum(t.get("replacements", 0) for t in types.values())
        total_quotes += replacements
        if dry_run:
            pages_n   = types.get("pages", {}).get("matched", 0)
            assign_n  = types.get("assignments", {}).get("matched", 0)
            discuss_n = types.get("discussions", {}).get("matched", 0)
        else:
            pages_n   = types.get("pages", {}).get("updated", 0)
            assign_n  = types.get("assignments", {}).get("updated", 0)
            discuss_n = types.get("discussions", {}).get("updated", 0)
        lines.append(row(course_id, pages_n, assign_n, discuss_n, replacements))

    lines += [
        divider,
        row("TOTAL", "", "", "", total_quotes),
        "",
        "  Columns show number of items that contained straight quotes." if dry_run
        else "  Columns show number of items updated on Canvas.",
        "" if not dry_run else "  Re-run without --dry-run to apply changes.",
        "",
    ]
    return lines


def _print_summary(summary: dict, *, dry_run: bool) -> Optional[Path]:
    lines = _build_summary_lines(summary, dry_run=dry_run)
    output = "\n".join(lines)
    print(output)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "curly_quotes_dryrun" if dry_run else "curly_quotes"
    log_path = REPO_ROOT / "logs" / f"{prefix}_{timestamp}.txt"
    log_path.write_text(output, encoding="utf-8")
    return log_path


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--course-ids",
        required=True,
        help="Comma-separated Canvas course IDs to process.",
    )
    p.add_argument(
        "--content-types",
        default="pages,assignments,discussions",
        help="Comma-separated subset to process: pages, assignments, discussions. (default: all)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing back to Canvas.",
    )
    p.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Log progress every N items per content type (0 to disable).",
    )
    p.add_argument(
        "-v", "--verbose",
        action="count",
        default=1,
        help="Increase verbosity (-v INFO, -vv DEBUG).",
    )
    args = p.parse_args(argv)

    setup_logging(verbosity=args.verbose)
    log = get_logger(artifact="curly-quotes-runner", course_id="-")

    base = os.getenv("CANVAS_TARGET_URL")
    token = os.getenv("CANVAS_TARGET_TOKEN")
    if not base or not token:
        log.error("CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN must be set in the environment.")
        return 2

    try:
        course_ids = _parse_course_ids(args.course_ids)
        content_types = _parse_content_types(args.content_types)
    except ValueError as exc:
        log.error(str(exc))
        return 2

    if not course_ids:
        log.warning("No course IDs provided.")
        return 0

    api = CanvasAPI(base, token)

    log.info(
        "Starting curly-quotes dry_run=%s courses=%s types=%s",
        args.dry_run,
        course_ids,
        sorted(content_types),
    )

    summary = fix_quotes(
        api=api,
        course_ids=course_ids,
        include_pages="pages" in content_types,
        include_assignments="assignments" in content_types,
        include_discussions="discussions" in content_types,
        dry_run=args.dry_run,
        progress_every=args.progress_every,
    )

    log_path = _print_summary(summary, dry_run=args.dry_run)
    print(f"Summary saved to: {log_path}")
    log.info("Finished curly-quotes dry_run=%s courses=%d", args.dry_run, len(course_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
