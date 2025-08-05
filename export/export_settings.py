# export/export_settings.py

import json
from pathlib import Path
from utils.api import source_api

def export_settings(course_id: int, output_dir: Path):
    """Export Canvas course settings to JSON"""
    settings = source_api.get(f"/courses/{course_id}/settings")
    course_dir = output_dir / str(course_id)
    course_dir.mkdir(parents=True, exist_ok=True)
    
    settings_file = course_dir / "course_settings.json"
    with settings_file.open("w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        
    print(f"Exported settings for course {course_id}")
