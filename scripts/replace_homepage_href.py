#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

# --- ensure repo root on sys.path ---
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from logging_setup import setup_logging, get_logger
from utils.api import CanvasAPI
from utils.html_postprocessor import replace_anchor_href


def _list_courses(api: CanvasAPI, account_id: int, *, published_only: bool) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {}
    if published_only:
        params["published"] = "true"
    courses = api.get(f"/accounts/{account_id}/courses", params=params)
    return courses if isinstance(courses, list) else []


def _course_name(course: Dict[str, Any]) -> str:
    name = course.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    code = course.get("course_code")
    if isinstance(code, str) and code.strip():
        return code.strip()
    return "unknown"


def _page_endpoint(course_id: int, slug: str) -> str:
    return f"/courses/{course_id}/pages/{quote(slug, safe='')}"


def _get_default_view(api: CanvasAPI, course_id: int) -> Optional[str]:
    try:
        course = api.get(f"/courses/{course_id}")
    except Exception:
        course = None
    if isinstance(course, dict):
        default_view = course.get("default_view")
        if isinstance(default_view, str) and default_view:
            return default_view

    try:
        settings = api.get(f"/courses/{course_id}/settings")
    except Exception:
        settings = None
    if isinstance(settings, dict):
        default_view = settings.get("default_view")
        if isinstance(default_view, str) and default_view:
            return default_view

    return None


def _default_report_path() -> Path:
    report_dir = REPO_ROOT / "logs" / "reports" / "s_and_r"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return report_dir / f"home_href_replace_report_{timestamp}.csv"


def _write_csv(report_path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "course_id",
        "course_name",
        "home_type",
        "front_page_slug",
        "replacements",
        "updated",
        "status",
        "error",
    ]
    with report_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Search/replace anchor hrefs on wiki front pages (home pages) for courses in an account.",
    )
    p.add_argument("--account-id", required=True, type=int, help="Canvas account id")
    p.add_argument("--target-href", required=True, help="Exact href to replace")
    p.add_argument("--replacement-href", required=True, help="Replacement href")
    p.add_argument("--dry-run", action="store_true", help="Report matches without updating Canvas.")
    p.add_argument(
        "--published-only",
        action="store_true",
        help="Restrict to published courses (default is all courses).",
    )
    p.add_argument(
        "--report-path",
        default=None,
        help="Optional output CSV path. Defaults to logs/reports/s_and_r/home_href_replace_report_*.csv",
    )
    p.add_argument("-v", "--verbose", action="count", default=1, help="Increase verbosity (-v, -vv).")
    args = p.parse_args(argv)

    setup_logging(verbosity=args.verbose)
    log = get_logger(artifact="home-search-replace-runner", course_id="-")

    base = os.getenv("CANVAS_TARGET_URL")
    token = os.getenv("CANVAS_TARGET_TOKEN")
    if not base or not token:
        log.error("Set CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN in the environment.")
        return 2

    api = CanvasAPI(base, token)

    courses = _list_courses(api, args.account_id, published_only=args.published_only)
    if not courses:
        log.warning("No courses found to process.")
        return 0

    report_path = Path(args.report_path) if args.report_path else _default_report_path()
    rows: List[Dict[str, Any]] = []

    for course in courses:
        course_id = course.get("id")
        if not isinstance(course_id, int):
            try:
                course_id = int(course_id)
            except (TypeError, ValueError):
                continue

        course_name = _course_name(course)
        clog = get_logger(artifact="home-search-replace", course_id=course_id)
        row = {
            "course_id": course_id,
            "course_name": course_name,
            "home_type": "",
            "front_page_slug": "",
            "replacements": 0,
            "updated": 0,
            "status": "",
            "error": "",
        }

        default_view = _get_default_view(api, course_id)
        row["home_type"] = default_view or "unknown"
        if default_view != "wiki":
            row["status"] = "skipped_non_wiki"
            rows.append(row)
            continue

        try:
            front_page = api.get(f"/courses/{course_id}/front_page")
        except Exception as exc:
            row["status"] = "front_page_fetch_failed"
            row["error"] = str(exc)
            rows.append(row)
            clog.warning("front page fetch failed err=%s", exc)
            continue

        if not isinstance(front_page, dict):
            row["status"] = "front_page_missing"
            rows.append(row)
            continue

        slug = front_page.get("url") or front_page.get("slug")
        if isinstance(slug, str):
            row["front_page_slug"] = slug
        else:
            row["status"] = "front_page_missing_slug"
            rows.append(row)
            continue

        body = front_page.get("body")
        if not isinstance(body, str) or not body:
            row["status"] = "front_page_no_body"
            rows.append(row)
            continue

        updated_html, replacements = replace_anchor_href(
            body,
            target_href=args.target_href,
            replacement_href=args.replacement_href,
        )
        row["replacements"] = replacements
        if replacements == 0:
            row["status"] = "no_match"
            rows.append(row)
            continue

        if args.dry_run:
            row["status"] = "dry_run"
            rows.append(row)
            continue

        try:
            api.put(
                _page_endpoint(course_id, slug),
                json={"wiki_page": {"body": updated_html}},
            )
            row["updated"] = 1
            row["status"] = "updated"
            rows.append(row)
        except Exception as exc:
            row["status"] = "update_failed"
            row["error"] = str(exc)
            rows.append(row)
            clog.warning("front page update failed err=%s", exc)

    _write_csv(report_path, rows)
    log.info("Report written to %s", report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
