# export/export_modules.py
import os, json
from utils.api import source_api
from utils.pagination import fetch_all

def export_modules(course_id, output_dir="export/data"):
    modules = fetch_all(f"/courses/{course_id}/modules")
    course_dir = os.path.join(output_dir, str(course_id))
    os.makedirs(course_dir, exist_ok=True)

    modules_metadata = []

    for mod in modules:
        module_id = mod["id"]
        items = fetch_all(f"/courses/{course_id}/modules/{module_id}/items")

        module_data = {
            "module_id": module_id,
            "title": mod["name"],
            "position": mod["position"],
            "items": []
        }

        for item in items:
            item_data = {
                "id": item["id"],
                "type": item["type"],
                "title": item.get("title"),
                "position": item["position"]
            }

            if item["type"] == "Page":
                item_data["page_url"] = item.get("page_url")

            module_data["items"].append(item_data)

        modules_metadata.append(module_data)

    meta_file = os.path.join(course_dir, "modules_metadata.json")
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(modules_metadata, f, indent=2)

    print(f"Exported {len(modules_metadata)} modules for course {course_id}")
    return modules_metadata