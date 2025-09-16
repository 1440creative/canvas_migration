# importers/import_course_settings.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

import requests
from logging_setup import get_logger


class CanvasLike(Protocol):
    api_root: str
    session: requests.Session
    def put(self, endpoint: str, **kwargs) -> requests.Response: ...
    def post(self, endpoint: str, **kwargs) -> requests.Response: ...
    def get(self, endpoint: str, **kwargs) -> requests.Response: ...


# ---------------- helpers ----------------

def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _safe_put_variants(canvas: CanvasLike, endpoint: str, settings: Dict[str, Any]) -> requests.Response:
    """
    PUT course settings with two shapes:
      1) {"course": {...}}  (preferred)
      2) {...}              (fallback)
    """
    try:
        resp = canvas.put(endpoint, json={"course": settings})
        resp.raise_for_status()
        return resp
    except requests.HTTPError as e:
        # Only fall back on client errors; re-raise 5xx and non-HTTP issues.
        if e.response is None or e.response.status_code < 400 or e.response.status_code >= 500:
            raise
        resp2 = canvas.put(endpoint, json=settings)
        resp2.raise_for_status()
        return resp2


def _try_enable_blueprint(canvas: CanvasLike, course_id: int, log) -> bool:
    """
    Best-effort: mark target course as a Blueprint.
    Requires admin perms; failures are logged and ignored.
    """
    try:
        endpoint = f"/api/v1/courses/{course_id}"
        payloads = [{"course": {"is_blueprint": True}}, {"is_blueprint": True}]
        for p in payloads:
            try:
                resp = canvas.put(endpoint, json=p)
                resp.raise_for_status()
                log.info("Enabled Blueprint mode on target course")
                return True
            except requests.HTTPError as e:
                # Try next shape on 4xx; abort on 2xx/5xx behavior anomalies.
                if e.response is None or e.response.status_code >= 500:
                    raise
        # If both shapes failed with 4xx, just log and continue.
        log.debug("Could not enable Blueprint mode (likely permissions)")
        return False
    except Exception as e:
        log.debug("enable-blueprint failed: %s", e)
        return False


def _apply_bp_restrictions(
    canvas: CanvasLike,
    course_id: int,
    restrictions: Dict[str, Any] | None,
    template_id: Optional[int],
    log,
) -> bool:
    """
    Attempt to PUT restrictions back to the template. We try a few payload shapes because
    Canvas instances differ in what they accept (form-encoded vs JSON names).
    """
    if not restrictions or not isinstance(restrictions, dict):
        return False

    # Choose endpoint: explicit template id or 'default'
    if template_id:
        endpoint = f"/api/v1/courses/{course_id}/blueprint_templates/{template_id}/restrictions"
    else:
        endpoint = f"/api/v1/courses/{course_id}/blueprint_templates/default/restrictions"

    attempts: list[Dict[str, Any]] = [
        {"blueprint_restrictions": restrictions},  # commonly accepted
        {"restrictions": restrictions},            # alternate
        restrictions,                              # raw
    ]

    for i, payload in enumerate(attempts, 1):
        try:
            resp = canvas.put(endpoint, json=payload)
            resp.raise_for_status()
            log.info("Applied Blueprint restrictions (attempt %d)", i)
            return True
        except requests.HTTPError as e:
            # Try next payload on 4xx; bail on 5xx.
            code = e.response.status_code if e.response is not None else None
            if code is None or code >= 500:
                log.exception("Server error applying Blueprint restrictions (attempt %d): %s", i, e)
                break
            log.debug("Restrictions payload attempt %d rejected with %s", i, code)
        except Exception as e:
            log.debug("Restrictions payload attempt %d failed: %s", i, e)

    log.warning("Failed to apply Blueprint restrictions (all attempts)")
    return False


# ---------------- public API ----------------

def import_course_settings(
    *,
    target_course_id: int,
    export_root: Path,
    canvas: CanvasLike,
    queue_blueprint_sync: bool = False,
) -> Dict[str, int]:
    """
    Import course-level settings and (optionally) trigger a Blueprint sync.

    Reads from {export_root}/course and {export_root}/blueprint:

      • course/settings.json -> PUT /api/v1/courses/:id
      • blueprint/blueprint_metadata.json:
          - if is_blueprint: best-effort enable blueprint on target
          - if restrictions present: PUT .../blueprint_templates/{id|default}/restrictions
      • queue_blueprint_sync=True -> POST .../blueprint_templates/default/migrations

    Returns counters:
      {
        "settings_applied": 0|1,
        "blueprint_enabled": 0|1,
        "restrictions_applied": 0|1,
        "blueprint_sync_queued": 0|1,
      }
    """
    log = get_logger(course_id=target_course_id, artifact="course")
    counters = {
        "settings_applied": 0,
        "blueprint_enabled": 0,
        "restrictions_applied": 0,
        "blueprint_sync_queued": 0,
    }

    # ---------- Course settings ----------
    course_dir = export_root / "course"
    settings_path = course_dir / "settings.json"
    if settings_path.exists():
        try:
            settings = _read_json(settings_path)
            if isinstance(settings, dict):
                log.info("Applying course settings from %s", settings_path)
                _safe_put_variants(canvas, f"/api/v1/courses/{target_course_id}", settings)
                counters["settings_applied"] = 1
            else:
                log.warning("settings.json is not an object; skipping")
        except Exception as e:
            log.exception("Failed to apply course settings: %s", e)
    else:
        log.info("No course settings at %s", settings_path)

    # ---------- Blueprint metadata ----------
    bp_dir = export_root / "blueprint"
    bp_meta_path = bp_dir / "blueprint_metadata.json"
    if bp_meta_path.exists():
        try:
            meta = _read_json(bp_meta_path)
        except Exception as e:
            log.warning("Could not read blueprint_metadata.json: %s", e)
            meta = None

        if isinstance(meta, dict) and meta.get("is_blueprint"):
            # 1) Ensure the target is blueprint (best-effort)
            if _try_enable_blueprint(canvas, target_course_id, log):
                counters["blueprint_enabled"] = 1

            # 2) Apply restrictions if present
            restrictions = meta.get("restrictions")
            template_id = None
            t = meta.get("template")
            if isinstance(t, dict):
                tid = t.get("id")
                if isinstance(tid, int):
                    template_id = tid

            if _apply_bp_restrictions(canvas, target_course_id, restrictions, template_id, log):
                counters["restrictions_applied"] = 1
        else:
            log.info("Blueprint metadata present but not marked is_blueprint=True; skipping apply.")
    else:
        log.info("No blueprint metadata at %s", bp_meta_path)

    # ---------- Optional: queue Blueprint sync ----------
    if queue_blueprint_sync:
        try:
            endpoint = f"/api/v1/courses/{target_course_id}/blueprint_templates/default/migrations"
            log.info("Queuing Blueprint sync")
            resp = canvas.post(endpoint, json={})
            resp.raise_for_status()
            counters["blueprint_sync_queued"] = 1
        except Exception as e:
            log.exception("Failed to queue Blueprint sync: %s", e)

    log.info(
        "Course settings import complete. settings_applied=%d blueprint_enabled=%d "
        "restrictions_applied=%d blueprint_sync_queued=%d",
        counters["settings_applied"],
        counters["blueprint_enabled"],
        counters["restrictions_applied"],
        counters["blueprint_sync_queued"],
    )
    return counters
