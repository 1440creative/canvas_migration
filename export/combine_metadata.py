#export/combine_metadata.py
import os
import json

def combine_metadata(course_id, output_dir="export/data"):
    """
    Combine modules, pages, assignments, and discussions metadata into
    a single course_structure.json that preserves module order and item mapping.
    """
    base_path = os.path.join(output_dir, str(course_id))

    def load_json(filename, default):
        path = os.path.join(base_path, filename)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        return default

    # Load metadata files
    modules = load_json("modules_metadata.json", [])
    assignments = {a["id"]: a for a in load_json("assignments_metadata.json", [])}
    discussions = {d["id"]: d for d in load_json("discussions_metadata.json", [])}
    pages = {}

    # Pages might use slug/page_url keys depending on export_pages format
    for p in load_json("pages_metadata.json", []):
        key = p.get("slug") or p.get("url")
        if key:
            pages[key] = p

    # Merge metadata into module items
    for mod in modules:
        for item in mod.get("items", []):
            if item["type"] == "Assignment":
                meta = assignments.get(item.get("content_id"))
                if meta:
                    item["metadata"] = meta
            elif item["type"] == "Discussion":
                meta = discussions.get(item.get("content_id"))
                if meta:
                    item["metadata"] = meta
            elif item["type"] == "Page":
                meta = pages.get(item.get("page_url"))
                if meta:
                    item["metadata"] = meta

    # Write combined file
    combined_file = os.path.join(base_path, "course_structure.json")
    os.makedirs(base_path, exist_ok=True)
    with open(combined_file, "w", encoding="utf-8") as f:
        json.dump(modules, f, indent=2)

    print(f"Combined metadata written to {combined_file}")
    return modules
