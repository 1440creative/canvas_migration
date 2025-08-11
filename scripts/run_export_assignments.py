# scripts/run_export_assignments.py
from pathlib import Path
from utils.api import source_api
from export.export_assignments import export_assignments

if __name__ == "__main__":
    export_root = Path("export/test_data")
    course_id = 86063  # https://canvas.sfu.ca/courses/86063 (EQH415 BPM)
    export_assignments(course_id, export_root=export_root, api=source_api)
