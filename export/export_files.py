#export/export_files.py
import os, json, requests
from utils.api import source_api
from utils.pagination import fetch_all

def export_files(course_id, output_dir="export/data"):
    """
    Export all files and folder metadata for a course.
    Downloads files and preserves folder structure.
    """
    course_dir = os.path.join(output_dir, str(course_id))
    files_dir = os.path.join(course_dir, "files")
    os.makedirs(files_dir, exist_ok=True)
    
    # get folders (to map folder IDs to paths)
    folders = fetch_all(f"/courses/{course_id}/folders")
    
    # use full_name to preserve hierarchy
    folder_map = {}
    for f in folders:
        #remove leading/trailing slash
        clean_path = f["full_name"].lstrip("/")
        folder_map[f["id"]] = clean_path
        
    
    # get files
    files = fetch_all(f"/courses/{course_id}/files")
    
    for f in files:
        folder_path = folder_map.get(f["folder_id"], "")
        local_folder = os.path.join(files_dir, folder_path)
        os.makedirs(local_folder, exist_ok=True)
        
        file_path = os.path.join(local_folder, f["filename"])
        download_url = f["url"]
        
    # download content
    r = requests.get(download_url)
    if r.status_code == 200:
            print("Saving file:", file_path)
            with open(file_path, "wb") as out:
                out.write(r.content)
    else:
        print(f"Failed to download {f['display_name']}")
#Save metadata
    metadata_path = os.path.join(course_dir, "files_metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as fmeta:
        json.dump(files, fmeta, indent=2)

    print(f"Exported {len(files)} files for course {course_id}")
    return files 