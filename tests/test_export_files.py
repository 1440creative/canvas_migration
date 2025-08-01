#tests/test_export_files.py
import os, json
from export.export_files import export_files

def test_export_files_with_nested_folders(tmp_output, requests_mock):
    course_id = 505
    base_url = "https://canvas.test/api/v1"

    # Mock nested folders
    requests_mock.get(
        f"{base_url}/courses/{course_id}/folders",
        json=[
            {"id": 10, "full_name": "Course Files"},
            {"id": 20, "full_name": "Course Files/Week 1"},
            {"id": 30, "full_name": "Course Files/Week 1/Images"}
        ]
    )

    # Mock files in different folders
    requests_mock.get(
        f"{base_url}/courses/{course_id}/files",
        json=[
            {
                "id": 100,
                "filename": "syllabus.pdf",
                "display_name": "Syllabus",
                "folder_id": 10,
                "url": "https://cdn.canvas.test/syllabus.pdf"
            },
            {
                "id": 200,
                "filename": "lecture1.mp4",
                "display_name": "Lecture 1",
                "folder_id": 20,
                "url": "https://cdn.canvas.test/lecture1.mp4"
            },
            {
                "id": 300,
                "filename": "diagram.png",
                "display_name": "Diagram",
                "folder_id": 30,
                "url": "https://cdn.canvas.test/diagram.png"
            }
        ]
    )

    # Mock downloads
    requests_mock.get("https://cdn.canvas.test/syllabus.pdf", content=b"PDFDATA")
    requests_mock.get("https://cdn.canvas.test/lecture1.mp4", content=b"MP4DATA")
    requests_mock.get("https://cdn.canvas.test/diagram.png", content=b"PNGDATA")

    # Patch API base URL
    from utils import api
    api.source_api.base_url = f"{base_url}/"

    files = export_files(course_id, output_dir=str(tmp_output))

    # Assertions
    assert len(files) == 3

    course_path = tmp_output / str(course_id)
    # Check that nested folders were created
    assert (course_path / "files" / "Course Files" / "syllabus.pdf").exists()
    assert (course_path / "files" / "Course Files" / "Week 1" / "lecture1.mp4").exists()
    assert (course_path / "files" / "Course Files" / "Week 1" / "Images" / "diagram.png").exists()

    # Check metadata file
    metadata_path = course_path / "files_metadata.json"
    assert metadata_path.exists()
    with open(metadata_path, "r") as f:
        meta = json.load(f)
    assert any(f["display_name"] == "Lecture 1" for f in meta)
