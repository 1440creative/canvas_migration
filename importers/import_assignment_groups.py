from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from logging_setup import get_logger


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _abs_url(api_root: str, endpoint_or_url: str) -> str:
    endpoint = (endpoint_or_url or "").strip()
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    root = api_root.rstrip("/")
    if not root.endswith("/api/v1"):
        root = root + "/api/v1"
    root += "/"
    ep = endpoint.lstrip("/")
    if ep.startswith("api/v1/"):
        ep = ep[len("api/v1/") :]
    return root + ep


def _post_assignment_group(canvas, endpoint_path: str, payload: Dict[str, Any]) -> int:
    url = _abs_url(canvas.api_root, endpoint_path)
    response = canvas.session.post(url, json=payload)

    status = getattr(response, "status_code", None)
    reason = getattr(response, "reason", "")

    body: Dict[str, Any] = {}
    try:
        body = response.json() or {}
    except Exception:
        body = {}

    if status and status >= 400:
        detail = body if body else getattr(response, "text", "")
        raise RuntimeError(f"Canvas responded {status} {reason or ''}: {detail}")

    if isinstance(body.get("id"), int):
        return int(body["id"])

    location = response.headers.get("Location") or response.headers.get("location")
    if location:
        follow_url = _abs_url(canvas.api_root, location)
        follow_resp = canvas.session.get(follow_url)
        try:
            follow_body = follow_resp.json() or {}
        except Exception:
            follow_body = {}
        if isinstance(follow_body.get("id"), int):
            return int(follow_body["id"])
        if isinstance(follow_body, dict) and follow_body.get("errors"):
            raise RuntimeError(
                f"Follow-up assignment group fetch returned errors: {follow_body['errors']}"
            )

    if isinstance(body, dict) and body.get("errors"):
        raise RuntimeError(f"Canvas returned assignment group errors: {body['errors']}")

    raise RuntimeError("Create assignment group did not return an id")


def import_assignment_groups(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
    id_map: Dict[str, Dict[Any, Any]],
) -> Dict[str, int]:
    log = get_logger(artifact="assignment_groups", course_id=target_course_id)
    base = export_root / "assignment_groups"

    counters = {"imported": 0, "failed": 0, "skipped": 0}

    if not base.exists():
        log.info("No assignment_groups directory found; nothing to import.")
        return counters

    meta_paths = sorted(base.rglob("assignment_group_metadata.json"))
    if not meta_paths:
        log.info("No assignment group metadata found under %s", base)
        return counters

    id_map.setdefault("assignment_groups", {})

    endpoint_path = f"/api/v1/courses/{target_course_id}/assignment_groups"

    for meta_path in meta_paths:
        g_dir = meta_path.parent
        try:
            meta = _read_json(meta_path)
            if not meta:
                log.warning("Skipping %s (empty metadata)", meta_path)
                counters["skipped"] += 1
                continue

            old_id = meta.get("id")
            name = meta.get("name") or g_dir.name

            payload: Dict[str, Any] = {"name": name}

            for key in ("position", "group_weight", "integration_data"):
                if key in meta and meta[key] is not None:
                    payload[key] = meta[key]

            rules = meta.get("rules")
            if rules:
                payload["rules"] = rules

            new_id = _post_assignment_group(canvas, endpoint_path, payload)

            if old_id is not None:
                try:
                    old_key = int(old_id)
                except (TypeError, ValueError):
                    old_key = old_id
                try:
                    id_map["assignment_groups"][old_key] = int(new_id)
                except (TypeError, ValueError):
                    id_map["assignment_groups"][old_key] = new_id

            counters["imported"] += 1
            log.info(
                "Created assignment group",
                extra={"old_id": old_id, "new_id": new_id, "name": name},
            )
        except Exception as exc:
            counters["failed"] += 1
            log.exception(
                "Failed to create assignment group from %s: %s",
                meta_path,
                exc,
            )

    log.info(
        "Assignment groups import complete.",
        extra={
            "imported": counters["imported"],
            "failed": counters["failed"],
            "skipped": counters["skipped"],
            "total": len(meta_paths),
        },
    )
    return counters
