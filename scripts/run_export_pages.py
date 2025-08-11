# scripts/run_export_pages.py (quick manual test)
from pathlib import Path
from utils.api import source_api
from export.export_pages import export_pages
    
if __name__ == "__main__":
    course_id = 86063 # https://canvas.sfu.ca/courses/86063 (EQH415 BPM)
    export_root = Path("export/test_data") 
    export_pages(course_id, export_root=export_root, api=source_api)
