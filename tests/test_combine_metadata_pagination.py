#tests/test_combine_metadata_pagination.py
import os, json
from export.combine_metadata import combine_metadata

def test_combine_metadata_with_pagination(tmp_output):
    course_id = 202
    base_path = tmp_output / str(course_id)
    os.makedirs(base_path)
    
    # fake modules metadata with two modules
    modules_meta = [
        {
            "id": 1,
            "name": "Module A",
            "position": 1,
            "items": [
                {"id": 11, "type": "Assignment", "content_id": 201, "title": "Essay A"},
                {"id": 12, "type": "Page", "page_url": "intro", "title": "Intro Page"}
            ]
        },
        {
            "id": 2,
            "name": "Module B",
            "position": 2,
            "items": [
                {"id": 21, "type": "Discussion", "content_id": 301, "title": "Discussion B"}
            ]
        }
    ]
    
    # Assignments metadata
    assignments_meta = [
        {"id": 201, "name": "Essay A", "points_possible": 10}
    ]

    # Discussions metadata
    discussions_meta = [
        {"id": 301, "title": "Discussion B", "message": "<p>Discuss here</p>"}
    ]

    # Pages metadata
    pages_meta = [
        {"slug": "intro", "title": "Intro Page", "body": "<h1>Welcome</h1>"}
    ]
    
     # Write fake metadata to disk
    with open(base_path / "modules_metadata.json", "w") as f:
        json.dump(modules_meta, f)
    with open(base_path / "assignments_metadata.json", "w") as f:
        json.dump(assignments_meta, f)
    with open(base_path / "discussions_metadata.json", "w") as f:
        json.dump(discussions_meta, f)
    with open(base_path / "pages_metadata.json", "w") as f:
        json.dump(pages_meta, f)
        
    #combine
    combined = combine_metadata(course_id, output_dir=str(tmp_output))

    # Assertions for pagination-like behavior
    assert len(combined) == 2
    assert combined[0]["items"][0]["metadata"]["name"] == "Essay A"
    assert combined[0]["items"][1]["metadata"]["title"] == "Intro Page"
    assert combined[1]["items"][0]["metadata"]["title"] == "Discussion B"

    # Ensure file written
    combined_file = base_path / "course_structure.json"
    assert combined_file.exists()
    with open(combined_file, "r") as f:
        data = json.load(f)
    assert len(data) == 2