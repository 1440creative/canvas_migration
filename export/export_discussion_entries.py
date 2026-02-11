# export/export_discussion_entries.py
from __future__ import annotations

import csv
import io
import logging
from pathlib import Path
from typing import Any, Dict, List

from utils.api import CanvasAPI
from utils.fs import ensure_dir, atomic_write, json_dumps_stable
from utils.strings import sanitize_slug

log = logging.getLogger("canvas_migrations")

CSV_COLUMNS = [
    "course_id",
    "course_name",
    "topic_id",
    "topic_title",
    "matched_keyword",
    "entry_id",
    "user_id",
    "user_name",
    "message_preview",
    "created_at",
]


def list_courses_in_subaccount(api: CanvasAPI, subaccount_id: int) -> List[dict]:
    """Return all courses in a Canvas subaccount."""
    courses = api.get(f"/accounts/{subaccount_id}/courses")
    if not isinstance(courses, list):
        return []
    return courses


def find_matching_discussions(
    api: CanvasAPI, course_id: int, keywords: List[str]
) -> List[dict]:
    """Return discussion topics whose title matches any keyword (case-insensitive)."""
    topics = api.get(f"/courses/{course_id}/discussion_topics")
    if not isinstance(topics, list):
        return []
    lower_kws = [kw.lower() for kw in keywords]
    matched = []
    for t in topics:
        title = (t.get("title") or "").lower()
        if any(kw in title for kw in lower_kws):
            t["course_id"] = course_id
            matched.append(t)
    return matched


def fetch_top_level_entries(
    api: CanvasAPI, course_id: int, topic_id: int
) -> List[dict]:
    """Return top-level entries for a discussion topic."""
    entries = api.get(f"/courses/{course_id}/discussion_topics/{topic_id}/entries")
    if not isinstance(entries, list):
        return []
    return entries


def _first_matched_keyword(title: str, keywords: List[str]) -> str:
    """Return the first keyword that matches the title (case-insensitive)."""
    lower_title = title.lower()
    for kw in keywords:
        if kw.lower() in lower_title:
            return kw
    return ""


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    """Write a flat CSV from a list of dicts."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(path, buf.getvalue())


def search_and_export(
    api: CanvasAPI,
    subaccount_id: int,
    keywords: List[str],
    output_dir: Path,
    course_code: str | None = None,
) -> List[dict]:
    """
    Orchestrator: list courses -> find matching discussions -> fetch entries
    -> write JSON + CSV.  Returns list of result dicts.

    If *course_code* is given, only courses whose ``course_code`` starts with
    that prefix (case-insensitive) are searched.
    """
    output_dir = Path(output_dir)
    ensure_dir(output_dir)

    courses = list_courses_in_subaccount(api, subaccount_id)
    log.info("found %d courses in subaccount %s", len(courses), subaccount_id)

    if course_code:
        prefix = course_code.upper()
        courses = [
            c for c in courses
            if (c.get("course_code") or "").upper().startswith(prefix)
        ]
        log.info("filtered to %d courses matching course code %r", len(courses), course_code)

    csv_rows: List[Dict[str, Any]] = []
    all_results: List[dict] = []

    for course in courses:
        course_id = course["id"]
        course_name = course.get("name", "")

        topics = find_matching_discussions(api, course_id, keywords)
        if not topics:
            continue

        log.info(
            "course %s: %d matching discussion(s)", course_id, len(topics)
        )

        for topic in topics:
            topic_id = topic["id"]
            topic_title = topic.get("title") or f"topic-{topic_id}"
            slug = sanitize_slug(topic_title) or f"topic-{topic_id}"
            matched_kw = _first_matched_keyword(topic_title, keywords)

            entries = fetch_top_level_entries(api, course_id, topic_id)

            # -- JSON output --
            topic_dir = (
                output_dir
                / str(course_id)
                / "discussion_entries"
                / f"{topic_id}_{slug}"
            )
            ensure_dir(topic_dir)

            meta = {
                "course_id": course_id,
                "course_name": course_name,
                "topic_id": topic_id,
                "title": topic_title,
                "matched_keyword": matched_kw,
                "entry_count": len(entries),
            }
            atomic_write(topic_dir / "topic_metadata.json", json_dumps_stable(meta))
            atomic_write(topic_dir / "entries.json", json_dumps_stable(entries))

            result = {**meta, "entries": entries}
            all_results.append(result)

            # -- CSV rows --
            if entries:
                for e in entries:
                    msg = (e.get("message") or "")[:200]
                    csv_rows.append({
                        "course_id": course_id,
                        "course_name": course_name,
                        "topic_id": topic_id,
                        "topic_title": topic_title,
                        "matched_keyword": matched_kw,
                        "entry_id": e.get("id", ""),
                        "user_id": e.get("user_id", ""),
                        "user_name": e.get("user_name", ""),
                        "message_preview": msg,
                        "created_at": e.get("created_at", ""),
                    })
            else:
                csv_rows.append({
                    "course_id": course_id,
                    "course_name": course_name,
                    "topic_id": topic_id,
                    "topic_title": topic_title,
                    "matched_keyword": matched_kw,
                    "entry_id": "",
                    "user_id": "",
                    "user_name": "",
                    "message_preview": "",
                    "created_at": "",
                })

    # Write aggregate CSV
    csv_path = output_dir / "discussion_entry_search_results.csv"
    _write_csv(csv_path, csv_rows)
    log.info("wrote %d CSV rows to %s", len(csv_rows), csv_path)

    return all_results
