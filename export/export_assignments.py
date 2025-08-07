import json, logging
from pathlib import Path
from typing import List, Dict, Any
from utils.pagination import fetch_all
from utils.logging import logger
from export.combine_metadata import combine_metadata

def export_assignments(course_id: int, output_dir: Path = Path("export/data")) -> List[Dict[str, Any]]:
    logger.info(f"Exporting assignments for course {course_id} to {output_dir}")

    course_dir = output_dir / str(course_id) / "assignments"
    course_dir.mkdir(parents=True, exist_ok=True)
    
    assignments = fetch_all(f"/courses/{course_id}/assignments")

    metadata = []

    for a in assignments:
        slug = f"assignment_{a['id']}"
        body = a.get("description", "")

        # Save HTML description
        file_path = course_dir / f"{slug}.html"
        with file_path.open("w", encoding="utf-8") as f:
            f.write(body or "")

        metadata.append({
            "id": a["id"],
            "name": a["name"],
            "points_possible": a.get("points_possible"),
            "due_at": a.get("due_at"),
            "published": a.get("published"),
            "html_file": f"{slug}.html"
        })

    meta_file = output_dir / str(course_id) / "assignments_metadata.json"
    with meta_file.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"Exported {len(metadata)} assignments for course {course_id}")

    # Update combined metadata JSON
    combine_metadata(course_id, output_dir=output_dir)

    return metadata