import os, json
from utils.pagination import fetch_all

def export_assignments(course_id, output_dir="export/data"):
    assignments = fetch_all(f"/courses/{course_id}/assignments")
    course_dir = os.path.join(output_dir, str(course_id), "assignments")
    os.makedirs(course_dir, exist_ok=True)

    metadata = []

    for a in assignments:
        slug = f"assignment_{a['id']}"
        body = a.get("description", "")

        # Save HTML description
        file_path = os.path.join(course_dir, f"{slug}.html")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(body or "")

        metadata.append({
            "id": a["id"],
            "name": a["name"],
            "points_possible": a.get("points_possible"),
            "due_at": a.get("due_at"),
            "published": a.get("published"),
            "html_file": f"{slug}.html"
        })

    meta_file = os.path.join(output_dir, str(course_id), "assignments_metadata.json")
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"Exported {len(metadata)} assignments for course {course_id}")
    return metadata
