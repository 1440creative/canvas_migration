# scripts/run_export_assignments.py
import os, sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from export.export_pages import export_pages
from pathlib import Path

if __name__ == "__main__":
    course_id = 86063  # https://canvas.sfu.ca/courses/86063 (EQH415 BPM)
    export_pages(course_id, output_dir=Path("export/test_data"))
