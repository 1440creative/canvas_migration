#!/usr/bin/env python3
"""
Download submitted file attachments for all courses in the target dump.

Reads the already-pulled submissions.json from each course's student_data/
directory and streams the attachment files to disk. Does NOT re-call the
Canvas API for student metadata — purely a download pass over local data.

Output per course:
  export/data/target_dump/{course_id}/student_data/attachments/
    {assignment_id}/{user_id}_{filename}

Usage:
  python scripts/pull_target_attachments.py
  python scripts/pull_target_attachments.py --dump-root export/data/target_dump
  python scripts/pull_target_attachments.py --course-ids 468 469
  python scripts/pull_target_attachments.py --dry-run
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
from utils.fs import ensure_dir

CHUNK = 1024 * 1024  # 1 MiB


def _read_json(path: Path) -> list | dict | None:
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


def _stream_download(session: requests.Session, url: str, dest: Path) -> bool:
    ensure_dir(dest.parent)
    with tempfile.NamedTemporaryFile(delete=False, dir=dest.parent) as tmp:
        tmp_path = Path(tmp.name)
    try:
        for attempt in range(1, 4):
            try:
                with session.get(url, stream=True, timeout=(5, 120)) as r:
                    if r.status_code in (403, 404, 410, 422):
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
                time.sleep(2.0 * attempt)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
    return False


def process_course(course_id: int, course_dir: Path, api: CanvasAPI,
                   dry_run: bool) -> tuple[int, int, int]:
    """Returns (attempted, downloaded, skipped)."""
    submissions_path = course_dir / "student_data" / "submissions.json"
    if not submissions_path.exists():
        print(f"    submissions.json not found — skipping")
        return 0, 0, 0

    submissions = _read_json(submissions_path)
    if not isinstance(submissions, list):
        print(f"    submissions.json unreadable — skipping")
        return 0, 0, 0

    att_root = course_dir / "student_data" / "attachments"
    attempted = downloaded = skipped = 0

    for sub in submissions:
        if not isinstance(sub, dict):
            continue
        aid = sub.get("assignment_id")
        uid = sub.get("user_id")
        for att in sub.get("attachments") or []:
            if not isinstance(att, dict):
                continue
            url = att.get("url")
            filename = (
                att.get("filename")
                or att.get("display_name")
                or f"file-{att.get('id', 'unknown')}"
            )
            if not (url and aid and uid):
                continue

            dest = att_root / str(aid) / f"{uid}_{filename}"
            attempted += 1

            if dest.exists():
                skipped += 1
                continue

            if dry_run:
                print(f"    [dry-run] {dest.relative_to(course_dir)}")
                continue

            ok = _stream_download(api.session, url, dest)
            if ok:
                downloaded += 1
            else:
                print(f"    WARNING: failed to download {filename} "
                      f"(assignment {aid}, user {uid})")

    return attempted, downloaded, skipped


def main() -> int:
    p = argparse.ArgumentParser(
        description="Download submitted file attachments from existing student data")
    p.add_argument("--dump-root", type=Path, default=Path("export/data/target_dump"),
                   help="Root of the target dump (default: export/data/target_dump)")
    p.add_argument("--course-ids", nargs="+", type=int, default=None,
                   help="Only process these course IDs (default: all in dump-root)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be downloaded without fetching")
    args = p.parse_args()

    if target_api is None:
        p.error("CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN must be set in .env or .env.local")

    dump_root = args.dump_root.resolve()
    if not dump_root.is_dir():
        p.error(f"Dump root not found: {dump_root}")

    course_ids = args.course_ids or _course_ids_from_dump(dump_root)
    print(f"Processing {len(course_ids)} courses in {dump_root}\n")

    total_attempted = total_downloaded = total_skipped = 0
    failed: list[int] = []

    for i, cid in enumerate(course_ids, 1):
        course_dir = dump_root / str(cid)
        if not course_dir.is_dir():
            print(f"[{i}/{len(course_ids)}] Course {cid}: directory not found, skipping")
            continue

        meta_path = course_dir / "course" / "course_metadata.json"
        name = ""
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            name = meta.get("name", "")
        except Exception:
            pass

        print(f"[{i}/{len(course_ids)}] Course {cid}: {name}")
        try:
            attempted, downloaded, skipped = process_course(
                cid, course_dir, target_api, args.dry_run)
            total_attempted += attempted
            total_downloaded += downloaded
            total_skipped += skipped
            print(f"    attachments found:    {attempted}")
            print(f"    downloaded:           {downloaded}")
            print(f"    already present:      {skipped}")
        except Exception as exc:
            print(f"    ERROR: {exc}", file=sys.stderr)
            failed.append(cid)

    print(f"\nDone.")
    print(f"  Total attachments found:    {total_attempted}")
    print(f"  Downloaded this run:        {total_downloaded}")
    print(f"  Already present (skipped):  {total_skipped}")
    print(f"  Courses succeeded: {len(course_ids) - len(failed)}/{len(course_ids)}")
    if failed:
        print(f"  Failed: {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
