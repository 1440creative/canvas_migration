# canvas_calibrator/exporters/new_quizzes_exporter.py
"""
Bulk-export New Quizzes QTI zips for a course.

For each New Quizzes assignment:
  1. GET  /api/quiz/v1/courses/{course_id}/quizzes         → list quizzes + assignment_id
  2. POST /api/quiz/v1/courses/{course_id}/quizzes/{id}/submissions/export  → trigger
  3. GET  .../export/{job_id}  every 2s until workflow_state == "generated"
  4. Download zip → export/data/cloud/{course_id}/quizzes_qti/{slug}.zip

Requires CANVAS_TARGET_URL and CANVAS_TARGET_TOKEN (loaded from .env.local).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

POLL_INTERVAL = 2       # seconds between status polls
POLL_TIMEOUT  = 300     # max seconds to wait per quiz


def _load_assignment_slugs(export_dir: Path) -> dict[int, str]:
    """
    Return {canvas_assignment_id: slug} by reading assignment_metadata.json files.
    slug = directory name, e.g. "005_module-1-self-assessment-1the-evolving-role-of-hr"
    """
    import json
    slugs: dict[int, str] = {}
    assignments_dir = export_dir / "assignments"
    if not assignments_dir.exists():
        return slugs
    for meta_file in assignments_dir.glob("*/assignment_metadata.json"):
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            aid = int(data.get("id", 0))
            if aid:
                slugs[aid] = meta_file.parent.name
        except Exception:
            continue
    return slugs


def export_new_quizzes(
    course_id: int,
    export_dir: Path,
    api,               # CanvasAPI instance (target)
    output_dir: Path | None = None,
) -> list[Path]:
    """
    Export all New Quizzes for a course to QTI zips.

    Args:
        course_id:   Canvas course ID
        export_dir:  path to export/data/cloud/{course_id}/
        api:         CanvasAPI instance pointing at the target server
        output_dir:  where to save zips; defaults to export_dir/quizzes_qti/

    Returns:
        list of paths to downloaded zip files
    """
    import requests

    if output_dir is None:
        output_dir = export_dir / "quizzes_qti"
    output_dir.mkdir(parents=True, exist_ok=True)

    assignment_slugs = _load_assignment_slugs(export_dir)
    log.info("Loaded %d assignment slugs", len(assignment_slugs))

    # 1. List all New Quizzes in the course
    log.info("Fetching New Quizzes list for course %s", course_id)
    quizzes = api.get(f"/api/quiz/v1/courses/{course_id}/quizzes")
    if not isinstance(quizzes, list):
        log.error("Unexpected response from New Quizzes list endpoint: %r", quizzes)
        return []

    log.info("Found %d New Quizzes", len(quizzes))

    downloaded: list[Path] = []

    for quiz in quizzes:
        quiz_id = quiz.get("id")
        assignment_id = quiz.get("assignment_id")
        title = quiz.get("title") or f"quiz-{quiz_id}"

        # Determine output filename from assignment slug if available
        slug = assignment_slugs.get(int(assignment_id or 0)) if assignment_id else None
        zip_name = f"{slug}.zip" if slug else f"quiz_{quiz_id}.zip"
        zip_path = output_dir / zip_name

        if zip_path.exists():
            log.info("Skipping %s — already exported", zip_name)
            downloaded.append(zip_path)
            continue

        log.info("Triggering QTI export for: %s (quiz_id=%s)", title, quiz_id)

        # 2. Trigger export
        try:
            resp = api.post(
                f"/api/quiz/v1/courses/{course_id}/quizzes/{quiz_id}/submissions/export"
            )
            resp_data = resp.json()
        except Exception as e:
            log.error("Failed to trigger export for quiz %s: %s", quiz_id, e)
            continue

        job_id = resp_data.get("id") or resp_data.get("job_id")
        if not job_id:
            log.error("No job_id in export response for quiz %s: %r", quiz_id, resp_data)
            continue

        # 3. Poll until generated
        poll_url = f"/api/quiz/v1/courses/{course_id}/quizzes/{quiz_id}/submissions/export/{job_id}"
        elapsed = 0
        download_url = None

        while elapsed < POLL_TIMEOUT:
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            try:
                status = api.get(poll_url)
            except Exception as e:
                log.warning("Poll error for quiz %s (job %s): %s", quiz_id, job_id, e)
                continue

            if not isinstance(status, dict):
                continue

            state = status.get("workflow_state", "")
            log.debug("Quiz %s export state: %s (elapsed %ds)", quiz_id, state, elapsed)

            if state == "generated":
                download_url = status.get("url")
                break
            elif state in ("failed", "error"):
                log.error("Export failed for quiz %s: %r", quiz_id, status)
                break

        if not download_url:
            log.error(
                "Export did not complete within %ds for quiz %s", POLL_TIMEOUT, quiz_id
            )
            continue

        # 4. Download zip
        try:
            log.info("Downloading zip for %s → %s", title, zip_name)
            # Use requests directly — download_url is a pre-signed S3 URL (no auth needed)
            dl_resp = requests.get(download_url, timeout=(5, 120), stream=True)
            dl_resp.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in dl_resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            log.info("Saved %s (%.1f KB)", zip_path.name, zip_path.stat().st_size / 1024)
            downloaded.append(zip_path)
        except Exception as e:
            log.error("Failed to download zip for quiz %s: %s", quiz_id, e)
            if zip_path.exists():
                zip_path.unlink()
            continue

    log.info("Exported %d/%d quizzes", len(downloaded), len(quizzes))
    return downloaded
