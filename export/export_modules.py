# export/export_modules.py
import os, json
from utils.pagination import fetch_all
from utils.api import source_api

def export_modules(course_id, output_dir="export/data"):
    modules = fetch_all(f"/courses/{course_id}/modules")
    course_dir = os.path.join(output_dir, str(course_id), "modules")
    os.makedirs(course_dir, exist_ok=True)

    metadata = []

    for m in modules:
        module_data = {
            "id": m["id"],
            "name": m["name"],
            "position": m["position"],
            "items": []
        }

        # Fetch items inside this module
        items = fetch_all(f"/courses/{course_id}/modules/{m['id']}/items")
        for item in items:
            module_data["items"].append({
                "id": item["id"],
                "title": item["title"],
                "type": item["type"],   # e.g. 'Page', 'Assignment', 'Discussion'
                "content_id": item.get("content_id"),  # for Assignments/Discussions
                "page_url": item.get("page_url"),      # for Pages
                "position": item["position"]
            })

        metadata.append(module_data)

    meta_file = os.path.join(output_dir, str(course_id), "modules_metadata.json")
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"Exported {len(metadata)} modules with items for course {course_id}")
    return metadata