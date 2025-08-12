# scripts/run_export_discussions.py
from pathlib import Path
from utils.api import source_api
from export.export_discussions import export_discussions
from logging_setup import setup_logging

if __name__ == "__main__":
    setup_logging(verbosity=1)
    course_id = 86063  # https://canvas.sfu.ca/courses/86063 (EQH415 BPM)
    export_root = Path("export/data")
    export_discussions(course_id, export_root=export_root, api=source_api)
