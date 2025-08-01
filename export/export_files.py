import os
import json
import requests
from utils.api import source_api
from utils.pagination import fetch_all

# 🔧 Configurable root folder for files with no folder mapping
ROOT_FOLDER_NAME = "Course Files"

def export_files(course_id, output_dir="export/data"):
    """
    Export all files and folder metadata for a course.
    Downloads files and preserves folder structure, including root-level files.
    """
    course_dir = os.path.join(output_dir, str(course_id))
    files_dir = os.path.join(course_dir, "files")
    os.makedirs(files_dir, exist_ok=True)

    # 1️⃣ Build folder map
    folders = fetch_all(f"/courses/{course_id}/folders")
    folder_map = {}
    for f in folders:
        clean_path = f["full_name"].strip("/")
        folder_map[f["id"]] = clean_path

    # 2️⃣ Fetch files
    files = fetch_all(f"/courses/{course_id}/files")

    for f in files:
        folder_path = folder_map.get(f["folder_id"])

        # ✅ Handle root-level files with no folder mapping
        if not folder_path:
            folder_path = ROOT_FOLDER_NAME

        local_folder = os.path.join(files_dir, folder_path)
        os.makedirs(local_folder, exist_ok=True)

        file_path = os.path.join(local_folder, f["filename"])
        print("Saving file:", file_path)

        r = requests.get(f["url"])
        if r.status_code == 200:
            with open(file_path, "wb") as out:
                out.write(r.content)
        else:
            print(f"⚠️ Failed to download {f['display_name']}")

    # 3️⃣ Save metadata
    metadata_path = os.path.join(course_dir, "files_metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as fmeta:
        json.dump(files, fmeta, indent=2)

    print(f"Exported {len(files)} files for course {course_id}")
    return files