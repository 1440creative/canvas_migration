#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, List, Set

# --- ensure repo root on sys.path ---
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from logging_setup import setup_logging, get_logger
from utils.api import CanvasAPI, list_blueprint_course_ids
from utils.search_replace_html import search_and_replace

CONTENT_TYPES: Set[str] = {"pages", "assignments", "discussions", "announcements"}


def _parse_course_ids(raw: str) -> List[int]:
    out: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError as exc:
            raise ValueError(f"Invalid course id: {part}") from exc
    return out


def _parse_content_types(raw: str) -> Set[str]:
    items = {item.strip().lower() for item in raw.split(",") if item.strip()}
    invalid = sorted(items - CONTENT_TYPES)
    if invalid:
        raise ValueError(f"Unknown content types: {', '.join(invalid)}")
    return items or set(CONTENT_TYPES)


def _iter_course_ids(
    api: CanvasAPI,
    *,
    account_id: int | None,
    course_ids: str | None,
) -> Iterable[int]:
    if course_ids:
        return _parse_course_ids(course_ids)
    if account_id is None:
        raise ValueError("Provide --course-ids or --account-id to list blueprint courses.")
    return list_blueprint_course_ids(api, account_id=account_id)


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Search/replace HTML links in blueprint courses (pages, assignments, discussions).",
    )
    p.add_argument("--account-id", type=int, default=None, help="Canvas account id for blueprint lookup")
    p.add_argument(
        "--course-ids",
        default=None,
        help="Comma-separated course ids (overrides --account-id blueprint lookup).",
    )
    p.add_argument(
        "--target-href",
        required=True,
        help="Exact href to replace (e.g., https://community.canvaslms.com/docs/DOC-10701).",
    )
    p.add_argument(
        "--replacement-href",
        required=True,
        help="Replacement href.",
    )
    p.add_argument(
        "--content-types",
        default="pages,assignments,discussions,announcements",
        help="Comma-separated list: pages,assignments,discussions,announcements.",
    )
    p.add_argument("--dry-run", action="store_true", help="Report matches without updating Canvas.")
    p.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Log progress every N items per content type (0 to disable).",
    )
    p.add_argument("-v", "--verbose", action="count", default=1, help="Increase verbosity (-v, -vv).")
    args = p.parse_args(argv)

    setup_logging(verbosity=args.verbose)
    log = get_logger(artifact="search-replace-runner", course_id="-")

    base = os.getenv("CANVAS_TARGET_URL")
    token = os.getenv("CANVAS_TARGET_TOKEN")
    if not base or not token:
        log.error("Set CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN in the environment.")
        return 2

    api = CanvasAPI(base, token)

    try:
        content_types = _parse_content_types(args.content_types)
        course_ids = list(_iter_course_ids(api, account_id=args.account_id, course_ids=args.course_ids))
    except ValueError as exc:
        log.error(str(exc))
        return 2

    if not course_ids:
        log.warning("No courses found to process.")
        return 0

    log.info("Starting search/replace", extra={"course_count": len(course_ids), "dry_run": args.dry_run})

    search_and_replace(
        api=api,
        course_ids=course_ids,
        target_href=args.target_href,
        replacement_href=args.replacement_href,
        include_pages="pages" in content_types,
        include_assignments="assignments" in content_types,
        include_discussions="discussions" in content_types,
        include_announcements="announcements" in content_types,
        dry_run=args.dry_run,
        progress_every=args.progress_every,
    )

    log.info("Search/replace finished", extra={"course_count": len(course_ids)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
