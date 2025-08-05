import os, json
from utils.pagination import fetch_all
from pathlib import Path
from typing import Any

def export_discussions(course_id: int, output_dir: Path = Path("export/data")) -> None:
    discussions = fetch_all(f"/courses/{course_id}/discussion_topics")
    course_dir = os.path.join(output_dir, str(course_id), "discussions")
    os.makedirs(course_dir, exist_ok=True)

    metadata = []

    for d in discussions:
        slug = f"discussion_{d['id']}"
        body = d.get("message", "")

        file_path = os.path.join(course_dir, f"{slug}.html")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(body or "")

        metadata.append({
            "id": d["id"],
            "title": d["title"],
            "discussion_type": d.get("discussion_type"),
            "published": d.get("published"),
            "html_file": f"{slug}.html"
        })

    meta_file = os.path.join(output_dir, str(course_id), "discussions_metadata.json")
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"Exported {len(metadata)} discussions for course {course_id}")
    return metadata