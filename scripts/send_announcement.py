#!/usr/bin/env python3
"""
Send an announcement to one or more Canvas courses on the target server.

Examples
--------
# From a manifest CSV (reads the SISID column)
PYTHONPATH=. python scripts/send_announcement.py \
    --manifest manifests/Canvas_Course_Production_Spreadsheet-20260507.csv \
    --title "Semester Reminder" \
    --message-file announcement_body.html

# Single course by numeric ID
PYTHONPATH=. python scripts/send_announcement.py \
    --course-id 12345 \
    --title "Important Update" \
    --message "<p>Please read the updated syllabus.</p>"

# Multiple courses from a plain text file (one ID per line)
PYTHONPATH=. python scripts/send_announcement.py \
    --course-ids-file my_courses.txt \
    --title "Semester Reminder" \
    --message-file announcement_body.html

# Dry run to preview without posting
PYTHONPATH=. python scripts/send_announcement.py \
    --manifest manifests/Canvas_Course_Production_Spreadsheet-20260507.csv \
    --title "Test" \
    --message "<p>Hello</p>" \
    --dry-run
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from dotenv import load_dotenv

from logging_setup import setup_logging, get_logger, DefaultContextFilter

REPORTS_DIR = Path(__file__).resolve().parents[1] / "logs" / "reports" / "announcements"


class CanvasLike(Protocol):
    def get(self, endpoint: str, **kwargs) -> Any: ...
    def post(self, endpoint: str, **kwargs) -> Any: ...


def send_announcements(
    *,
    course_selectors: List[str],
    title: str,
    message: str,
    canvas: CanvasLike,
    delayed_post_at: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, int]:
    """
    Post an announcement to each course in course_selectors.

    Each selector is either a numeric string ("12345") or a Canvas SIS ID
    reference ("sis_course_id:BAC115-ON12641"), used directly in the URL.

    Returns counters: {"sent": n, "failed": n, "total": n}
    """
    log = get_logger(artifact="send-announcement", course_id=0)
    counters = {"sent": 0, "failed": 0, "total": len(course_selectors)}

    payload: Dict[str, Any] = {
        "title": title,
        "message": message,
        "is_announcement": True,
    }
    if delayed_post_at:
        payload["delayed_post_at"] = delayed_post_at

    for selector in course_selectors:
        endpoint = f"/api/v1/courses/{selector}/discussion_topics"
        if dry_run:
            log.info("DRY-RUN course=%s title=%r", selector, title)
            counters["sent"] += 1
            continue
        try:
            resp = canvas.post(endpoint, json=payload)
            new_id: Optional[int] = None
            try:
                body = resp.json() if hasattr(resp, "json") else resp
                if isinstance(body, dict):
                    new_id = body.get("id")
            except Exception:
                pass
            counters["sent"] += 1
            log.info("Posted course=%s announcement_id=%s title=%r", selector, new_id, title)
        except Exception as exc:
            counters["failed"] += 1
            log.error("Failed course=%s: %s", selector, exc)

    return counters


def _resolve_selectors(
    selectors: List[str],
    canvas: CanvasLike,
    log: logging.Logger,
    account_id: int = 1,
) -> tuple[List[str], int]:
    """
    Resolve sis_course_id: selectors to numeric course IDs by searching the
    accounts courses endpoint with the SIS ID as the search term, then matching
    on a course whose name starts with that ID.
    Numeric selectors pass through unchanged.
    Returns (resolved_selectors, n_failed).
    """
    resolved = []
    failed = 0
    for selector in selectors:
        if not selector.startswith("sis_course_id:"):
            resolved.append(selector)
            continue
        sis_id = selector[len("sis_course_id:"):]
        try:
            results = canvas.get(
                f"/api/v1/accounts/{account_id}/courses",
                params={"search_term": sis_id, "per_page": 10},
            )
            match = None
            if isinstance(results, list):
                match = next(
                    (c for c in results
                     if isinstance(c, dict) and c.get("name", "").startswith(sis_id)),
                    None,
                )
            if match and match.get("id"):
                course_id = str(match["id"])
                log.debug("Resolved %s -> course_id %s (%s)", sis_id, course_id, match.get("name"))
                resolved.append(course_id)
            else:
                log.error("Could not resolve %s: no course found matching that name", sis_id)
                failed += 1
        except Exception as exc:
            log.error("Could not resolve %s: %s", sis_id, exc)
            failed += 1
    return resolved, failed


def _load_from_manifest(path: str) -> List[str]:
    """Read the SISID column from a CSV and return sis_course_id: prefixed selectors."""
    try:
        f = open(path, encoding="utf-8-sig")
    except OSError as exc:
        print(f"ERROR: cannot read --manifest {path!r}: {exc}", file=sys.stderr)
        sys.exit(2)

    with f:
        reader = csv.DictReader(f)
        if "SISID" not in (reader.fieldnames or []):
            print(f"ERROR: no 'SISID' column found in {path}", file=sys.stderr)
            sys.exit(2)
        selectors = []
        for row in reader:
            sis_id = (row.get("SISID") or "").strip()
            if sis_id:
                selectors.append(f"sis_course_id:{sis_id}")

    if not selectors:
        print(f"ERROR: no SIS IDs found in SISID column of {path}", file=sys.stderr)
        sys.exit(2)

    return selectors


def _load_from_ids_file(path: str) -> List[str]:
    """Read one numeric course ID per line, ignoring blanks and # comments."""
    try:
        lines = open(path, encoding="utf-8").readlines()
    except OSError as exc:
        print(f"ERROR: cannot read --course-ids-file {path!r}: {exc}", file=sys.stderr)
        sys.exit(2)

    selectors: List[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not stripped.isdigit():
            print(f"ERROR: non-integer course ID {stripped!r} in {path}", file=sys.stderr)
            sys.exit(2)
        selectors.append(stripped)

    if not selectors:
        print(f"ERROR: no course IDs found in {path}", file=sys.stderr)
        sys.exit(2)

    return selectors


def _load_course_selectors(args: argparse.Namespace) -> List[str]:
    if args.manifest:
        return _load_from_manifest(args.manifest)
    if args.course_ids_file:
        return _load_from_ids_file(args.course_ids_file)
    # --course-id (list of ints from argparse)
    return [str(cid) for cid in args.course_ids]


def _load_message(args: argparse.Namespace) -> str:
    if args.message:
        return args.message
    path = args.message_file
    try:
        return open(path, encoding="utf-8").read()
    except OSError as exc:
        print(f"ERROR: cannot read --message-file {path!r}: {exc}", file=sys.stderr)
        sys.exit(2)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Send an announcement to one or more Canvas courses on the target server."
    )

    course_group = p.add_mutually_exclusive_group(required=True)
    course_group.add_argument(
        "--manifest", metavar="FILE",
        help="CSV manifest file; reads the SISID column to determine target courses",
    )
    course_group.add_argument(
        "--course-id", dest="course_ids", type=int, action="append", metavar="ID",
        help="Numeric course ID (repeatable: --course-id 1 --course-id 2)",
    )
    course_group.add_argument(
        "--course-ids-file", metavar="FILE",
        help="Text file with one numeric course ID per line (blank lines and # comments ignored)",
    )

    p.add_argument("--title", required=True, help="Announcement title")

    msg_group = p.add_mutually_exclusive_group(required=True)
    msg_group.add_argument("--message", help="Announcement body HTML (inline)")
    msg_group.add_argument("--message-file", metavar="FILE", help="Path to an HTML file to use as the body")

    p.add_argument(
        "--delayed-post-at", metavar="DATETIME",
        help="ISO 8601 datetime to schedule the announcement (e.g. 2026-09-01T09:00:00Z)",
    )
    p.add_argument(
        "--account-id", type=int, default=1, metavar="ID",
        help="Canvas account ID used when resolving SIS IDs by course name search (default: 1)",
    )
    p.add_argument("--dry-run", action="store_true", help="Log what would be posted without making API calls")
    p.add_argument("--preview", action="store_true", help="Print the announcement title and full HTML body before running (use with --dry-run to verify content)")
    p.add_argument("-v", "--verbose", action="count", default=1)

    return p.parse_args()


def _add_file_handler(verbosity: int) -> Path:
    """Add a timestamped file handler to the canvas_migrations logger."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    log_path = REPORTS_DIR / f"{timestamp}_send_announcement.log"

    level = logging.DEBUG if verbosity >= 2 else logging.INFO
    fmt = (
        "%(asctime)s %(levelname)s "
        "course=%(course_id)s artifact=%(artifact)s "
        "%(message)s"
    )
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(DefaultContextFilter())

    logging.getLogger("canvas_migrations").addHandler(handler)
    return log_path


def main() -> int:
    load_dotenv()
    args = _parse_args()
    setup_logging(verbosity=args.verbose)
    log_path = _add_file_handler(args.verbose)
    log = get_logger(artifact="send-announcement", course_id=0)
    log.info("Logging to %s", log_path)

    from utils.api import target_api
    if target_api is None:
        log.error("target_api is not configured. Set CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN.")
        return 2

    course_selectors = _load_course_selectors(args)
    original_count = len(course_selectors)
    message = _load_message(args)

    resolve_failed = 0
    if not args.dry_run:
        log.info("Resolving %d SIS ID(s) to Canvas course IDs...", original_count)
        course_selectors, resolve_failed = _resolve_selectors(course_selectors, target_api, log, account_id=args.account_id)
        log.info("Resolved %d course(s); %d failed to resolve", len(course_selectors), resolve_failed)

    if args.preview:
        print("-" * 60)
        print(f"TITLE:   {args.title}")
        print(f"MESSAGE:\n{message}")
        print("-" * 60)

    log.info(
        "Sending announcement %r to %d course(s)%s",
        args.title,
        len(course_selectors),
        " [DRY RUN]" if args.dry_run else "",
    )

    counters = send_announcements(
        course_selectors=course_selectors,
        title=args.title,
        message=message,
        canvas=target_api,
        delayed_post_at=args.delayed_post_at,
        dry_run=args.dry_run,
    )
    counters["failed"] += resolve_failed
    counters["total"] = original_count

    summary = (
        f"Done. sent={counters['sent']} failed={counters['failed']} total={counters['total']}"
    )
    log.info(summary)
    print(summary)
    print(f"Report written to: {log_path}")

    return 1 if counters["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
