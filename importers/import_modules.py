from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from logging_setup import get_logger

log = get_logger(artifact="modules")


def _read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _follow_location_for_id(canvas, loc_url: str) -> Optional[int]:
    try:
        r = canvas.session.get(loc_url)
        r.raise_for_status()
        try:
            body = r.json()
        except Exception:
            body = {}
        mid = body.get("id")
        return int(mid) if isinstance(mid, int) else None
    except Exception:
        return None


def import_modules(
    *,
    target_course_id: int,
    export_root: Path,
    canvas,
    id_map: Dict[str, Dict[Any, Any]],
) -> Dict[str, int]:
    """
    Create modules from export/modules/modules.json.
    """
    modules_path = export_root / "modules" / "modules.json"
    data = _read_json(modules_path) or []
    created = 0
    failed = 0

    id_map.setdefault("modules", {})

    for m in data:
        name = (m or {}).get("name") or "Untitled Module"
        payload = {"name": name}
        try:
            resp = canvas.post(f"/api/v1/courses/{target_course_id}/modules", json={"module": payload})
            try:
                body = resp.json()
            except Exception:
                body = {}
            new_id = body.get("id")
            if not isinstance(new_id, int):
                loc = resp.headers.get("Location")
                if loc:
                    new_id = _follow_location_for_id(canvas, loc)

            if isinstance(new_id, int):
                created += 1
                src_id = (m or {}).get("id")
                if isinstance(src_id, int):
                    id_map["modules"][src_id] = new_id
            else:
                log.error("failed to create module (no id) name=%r", name)
                failed += 1
        except Exception as e:
            log.error("failed to create module name=%r error=%s", name, e)
            failed += 1

    log.info(
        "Modules import complete. modules_created=%d modules_failed=%d total_modules=%d",
        created, failed, len(data),
    )
    return {"modules_created": created, "modules_failed": failed, "total_modules": len(data)}
