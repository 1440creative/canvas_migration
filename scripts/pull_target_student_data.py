#!/usr/bin/env python3
"""
Pull student data (grades, submissions, quiz attempts, discussion entries)
for courses already exported to export/data/target_dump/.

Reads course IDs from the existing dump folder and writes student data
into a student_data/ subfolder inside each course directory:

  export/data/target_dump/{course_id}/
    student_data/
      enrollments.json              # roster + current/final grades
      submissions.json              # all assignment submissions (all students, bulk)
      quiz_submissions/
        {quiz_id}.json
      discussion_entries/
        {topic_id}.json
      attachments/                  # submitted files (opt-in via --attachments)
        {assignment_id}/{user_id}_{filename}

Usage:
  python scripts/pull_target_student_data.py
  python scripts/pull_target_student_data.py --dump-root export/data/target_dump
  python scripts/pull_target_student_data.py --course-ids 468 469 --attachments
  python scripts/pull_target_student_data.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(str(REPO_ROOT / ".env"))
    load_dotenv(str(REPO_ROOT / ".env.local"), override=True)
except ImportError:
    pass

import requests
from utils.api import CanvasAPI, target_api
from utils.fs import atomic_write, ensure_dir, json_dumps_stable

CHUNK = 1024 * 1024  # 1 MiB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _course_ids_from_dump(dump_root: Path) -> list[int]:
    ids = []
    for d in sorted(dump_root.iterdir()):
        if d.is_dir():
            try:
                ids.append(int(d.name))
            except ValueError:
                pass
    return ids


def _quiz_ids_from_export(course_dir: Path) -> list[int]:
    ids = []
    for meta in sorted(course_dir.glob("quizzes/*/quiz_metadata.json")):
        data = _read_json(meta)
        if isinstance(data, dict) and data.get("id"):
            try:
                ids.append(int(data["id"]))
            except (TypeError, ValueError):
                pass
    return ids


def _discussion_ids_from_export(course_dir: Path) -> list[int]:
    ids = []
    for meta in sorted(course_dir.glob("discussions/*/discussion_metadata.json")):
        data = _read_json(meta)
        if isinstance(data, dict) and data.get("id"):
            try:
                ids.append(int(data["id"]))
            except (TypeError, ValueError):
                pass
    return ids


def _stream_download(api: CanvasAPI, url: str, dest: Path) -> bool:
    ensure_dir(dest.parent)
    with tempfile.NamedTemporaryFile(delete=False, dir=dest.parent) as tmp:
        tmp_path = Path(tmp.name)
    try:
        for attempt in range(1, 4):
            try:
                with api.session.get(url, stream=True, timeout=(5, 60)) as r:
                    if r.status_code in (404, 410, 422):
                        tmp_path.unlink(missing_ok=True)
                        return False
                    r.raise_for_status()
                    with open(tmp_path, "wb") as out:
                        for chunk in r.iter_content(CHUNK):
                            if chunk:
                                out.write(chunk)
                os.replace(tmp_path, dest)
                return True
            except (requests.ConnectionError, requests.Timeout):
                if attempt >= 3:
                    tmp_path.unlink(missing_ok=True)
                    return False
                time.sleep(1.5 * attempt)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# Per-course exporters
# ---------------------------------------------------------------------------

def export_enrollments(course_id: int, out_dir: Path, api: CanvasAPI, dry_run: bool) -> int:
    """Fetch student enrollments including current and final grades."""
    params = {
        "type[]": "StudentEnrollment",
        "state[]": ["active", "completed", "inactive"],
        "include[]": ["current_grades", "final_grades", "total_scores"],
        "per_page": 100,
    }
    if dry_run:
        print("    [dry-run] GET enrollments")
        return 0
    data = api.get(f"/courses/{course_id}/enrollments", params=params)
    if not isinstance(data, list):
        print(f"    WARNING: unexpected enrollments response for course {course_id}")
        return 0
    atomic_write(out_dir / "enrollments.json", json_dumps_stable(data))
    return len(data)


def export_submissions(course_id: int, out_dir: Path, api: CanvasAPI,
                       download_attachments: bool, dry_run: bool) -> int:
    """Bulk-fetch all student submissions across all assignments."""
    params = {
        "student_ids[]": "all",
        "include[]": ["submission_history", "rubric_assessment", "attachments",
                       "submission_comments", "assignment"],
        "per_page": 100,
    }
    if dry_run:
        print("    [dry-run] GET students/submissions")
        return 0
    data = api.get(f"/courses/{course_id}/students/submissions", params=params)
    if not isinstance(data, list):
        print(f"    WARNING: unexpected submissions response for course {course_id}")
        return 0
    atomic_write(out_dir / "submissions.json", json_dumps_stable(data))

    if download_attachments:
        att_root = out_dir / "attachments"
        for sub in data:
            if not isinstance(sub, dict):
                continue
            aid = sub.get("assignment_id")
            uid = sub.get("user_id")
            for att in sub.get("attachments") or []:
                if not isinstance(att, dict):
                    continue
                url = att.get("url")
                filename = att.get("filename") or att.get("display_name") or f"file-{att.get('id')}"
                if url and aid and uid:
                    dest = att_root / str(aid) / f"{uid}_{filename}"
                    _stream_download(api, url, dest)

    return len(data)


def export_quiz_submissions(course_id: int, quiz_ids: list[int], out_dir: Path,
                             api: CanvasAPI, dry_run: bool) -> int:
    """Fetch per-quiz submission attempts for all students."""
    if not quiz_ids:
        return 0
    qsub_dir = out_dir / "quiz_submissions"
    ensure_dir(qsub_dir)
    total = 0
    for qid in quiz_ids:
        if dry_run:
            print(f"    [dry-run] GET quizzes/{qid}/submissions")
            continue
        try:
            data = api.get(f"/courses/{course_id}/quizzes/{qid}/submissions",
                           params={"include[]": ["submission", "quiz", "user"], "per_page": 100})
            entries = data.get("quiz_submissions", data) if isinstance(data, dict) else data
            if isinstance(entries, list):
                atomic_write(qsub_dir / f"{qid}.json", json_dumps_stable(entries))
                total += len(entries)
        except Exception as exc:
            print(f"    WARNING: quiz {qid} submissions failed: {exc}")
    return total


def export_discussion_entries(course_id: int, topic_ids: list[int], out_dir: Path,
                               api: CanvasAPI, dry_run: bool) -> int:
    """Fetch all student posts and replies for each discussion topic."""
    if not topic_ids:
        return 0
    disc_dir = out_dir / "discussion_entries"
    ensure_dir(disc_dir)
    total = 0
    for tid in topic_ids:
        if dry_run:
            print(f"    [dry-run] GET discussion_topics/{tid}/entries")
            continue
        try:
            entries = api.get(f"/courses/{course_id}/discussion_topics/{tid}/entries",
                              params={"per_page": 100})
            if isinstance(entries, list):
                # Fetch replies for each top-level entry
                full_entries = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    eid = entry.get("id")
                    if eid:
                        try:
                            replies = api.get(
                                f"/courses/{course_id}/discussion_topics/{tid}/entries/{eid}/replies",
                                params={"per_page": 100},
                            )
                            entry["replies"] = replies if isinstance(replies, list) else []
                        except Exception:
                            entry["replies"] = []
                    full_entries.append(entry)
                atomic_write(disc_dir / f"{tid}.json", json_dumps_stable(full_entries))
                total += len(full_entries)
        except Exception as exc:
            print(f"    WARNING: discussion {tid} entries failed: {exc}")
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_course(course_id: int, course_dir: Path, api: CanvasAPI,
                   download_attachments: bool, dry_run: bool) -> bool:
    out_dir = course_dir / "student_data"
    if not dry_run:
        ensure_dir(out_dir)

    quiz_ids = _quiz_ids_from_export(course_dir)
    discussion_ids = _discussion_ids_from_export(course_dir)

    try:
        n_enroll = export_enrollments(course_id, out_dir, api, dry_run)
        print(f"    enrollments:          {n_enroll}")

        n_subs = export_submissions(course_id, out_dir, api, download_attachments, dry_run)
        print(f"    submissions:          {n_subs}")

        n_qsubs = export_quiz_submissions(course_id, quiz_ids, out_dir, api, dry_run)
        print(f"    quiz submissions:     {n_qsubs} (across {len(quiz_ids)} quizzes)")

        n_disc = export_discussion_entries(course_id, discussion_ids, out_dir, api, dry_run)
        print(f"    discussion entries:   {n_disc} (across {len(discussion_ids)} topics)")

        return True
    except Exception as exc:
        print(f"    ERROR: {exc}", file=sys.stderr)
        return False


def main() -> int:
    p = argparse.ArgumentParser(description="Pull student data into existing target dump folders")
    p.add_argument("--dump-root", type=Path, default=Path("export/data/target_dump"),
                   help="Root of the target dump (default: export/data/target_dump)")
    p.add_argument("--course-ids", nargs="+", type=int, default=None,
                   help="Only process these course IDs (default: all in dump-root)")
    p.add_argument("--attachments", action="store_true",
                   help="Download submitted files (can be large)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be fetched without making API calls")
    args = p.parse_args()

    if target_api is None:
        p.error("CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN must be set in .env or .env.local")

    dump_root = args.dump_root.resolve()
    if not dump_root.is_dir():
        p.error(f"Dump root not found: {dump_root} — run pull_target_courses.py first")

    if args.course_ids:
        course_ids = args.course_ids
    else:
        course_ids = _course_ids_from_dump(dump_root)

    print(f"Processing {len(course_ids)} courses in {dump_root}\n")

    failed: list[int] = []
    for i, cid in enumerate(course_ids, 1):
        course_dir = dump_root / str(cid)
        if not course_dir.is_dir():
            print(f"[{i}/{len(course_ids)}] Course {cid}: directory not found, skipping")
            continue

        meta = _read_json(course_dir / "course" / "course_metadata.json") or {}
        name = meta.get("name") or "(unknown)"
        print(f"[{i}/{len(course_ids)}] Course {cid}: {name}")

        ok = process_course(cid, course_dir, target_api, args.attachments, args.dry_run)
        if not ok:
            failed.append(cid)

    print(f"\nDone. {len(course_ids) - len(failed)}/{len(course_ids)} courses succeeded.")
    if failed:
        print(f"Failed: {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
