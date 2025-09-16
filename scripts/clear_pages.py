#!/usr/bin/env python3
from __future__ import annotations

import argparse
from typing import List, Dict, Any
from dotenv import load_dotenv

from logging_setup import setup_logging, get_logger
from utils.api import target_api

"""
import path workaround example:

PYTHONPATH=. python scripts/clear_pages.py --target-course-id 546 --dry-run -v


"""


"""
scripts/clear_pages.py

Delete (most) pages from a target Canvas course using your configured target_api.
By default, it keeps the current front page and anything you opt to keep.

Examples
--------
# Dry run: see what would be deleted
python scripts/clear_pages.py --target-course-id 12345 --dry-run -v

# Really delete all pages except the front page
python scripts/clear_pages.py --target-course-id 12345 -y -vv

# Keep front page + anything starting with "Getting Started:" and specific slugs
python scripts/clear_pages.py --target-course-id 12345 -y \
  --keep-title-prefix "Getting Started:" \
  --keep-slug "welcome" --keep-slug "syllabus" -vv
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Delete pages from a target Canvas course (safe by default).")
    p.add_argument("--target-course-id", required=True, type=int, help="Target Canvas course ID")
    p.add_argument("-y", "--yes", action="store_true", help="Do not prompt for confirmation")
    p.add_argument("--dry-run", action="store_true", help="Show what would be deleted; no API calls to DELETE")
    p.add_argument("-v", "--verbose", action="count", default=1, help="Increase verbosity")

    keep = p.add_argument_group("Keep filters (non-destructive)")
    keep.add_argument("--no-keep-front-page", dest="keep_front", action="store_false",
                      help="Allow deletion of the current front page (NOT recommended)")
    keep.add_argument("--keep-title-prefix", action="append", default=[],
                      help="Keep any page whose title starts with this prefix (repeatable)")
    keep.add_argument("--keep-slug", action="append", default=[],
                      help="Keep any page whose slug matches exactly (repeatable)")

    p.set_defaults(keep_front=True)
    return p.parse_args()


def _list_pages(course_id: int) -> List[Dict[str, Any]]:
    # Canvas returns a list with pagination; your CanvasAPI.get handles pagination transparently
    pages = target_api.get(f"/api/v1/courses/{course_id}/pages")
    return pages if isinstance(pages, list) else []


def _front_page_slug(course_id: int) -> str | None:
    try:
        fp = target_api.get(f"/api/v1/courses/{course_id}/front_page")
        if isinstance(fp, dict):
            return fp.get("url") or fp.get("slug")
    except Exception:
        # If the instance has no front page API enabled, just return None.
        return None
    return None


def main() -> int:
    load_dotenv()
    args = parse_args()
    setup_logging(verbosity=args.verbose)
    log = get_logger(artifact="pages-clear", course_id=args.target_course_id)

    if target_api is None:
        log.error("target_api is not configured. Set CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN in your .env")
        return 2

    log.info("Scanning pages in course_id=%s", args.target_course_id)
    front_slug = _front_page_slug(args.target_course_id) if args.keep_front else None
    pages = _list_pages(args.target_course_id)

    keep_slugs = set(s.strip() for s in args.keep_slug if s and s.strip())
    keep_prefixes = [s for s in args.keep_title_prefix if s is not None]

    to_delete: List[Dict[str, Any]] = []
    for p in pages:
        slug = str(p.get("url") or "")
        title = str(p.get("title") or "")
        if not slug:
            # Defensive: skip unknown records
            continue

        # Keep rules
        if args.keep_front and front_slug and slug == front_slug:
            continue
        if slug in keep_slugs:
            continue
        if any(title.startswith(pref) for pref in keep_prefixes):
            continue

        to_delete.append(p)

    log.info("Found %d page(s); will delete %d, keep %d",
             len(pages), len(to_delete), len(pages) - len(to_delete))

    if args.dry_run:
        for p in to_delete:
            log.info("DRY-RUN delete slug=%s title=%s", p.get("url"), p.get("title"))
        log.info("Dry run complete. No pages were deleted.")
        return 0

    if not args.yes:
        log.warning("Refusing to proceed without --yes. Aborting.")
        return 1

    # Perform deletions
    deleted = failed = 0
    for p in to_delete:
        slug = p.get("url")
        title = p.get("title")
        try:
            target_api.delete(f"/api/v1/courses/{args.target_course_id}/pages/{slug}")
            deleted += 1
            log.info("Deleted page slug=%s title=%s", slug, title)
        except Exception as e:
            failed += 1
            log.exception("Failed to delete page slug=%s title=%s: %s", slug, title, e)

    log.info("Done. deleted=%d failed=%d kept=%d total=%d",
             deleted, failed, len(pages) - len(to_delete), len(pages))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
