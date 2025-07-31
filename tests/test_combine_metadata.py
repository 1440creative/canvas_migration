import os, json
from export.combine_metadata import combine_metadata

def test_combine_metadata(tmp_output):
    course_id = 101
    base_path = tmp_output / str(course_id)
    os.makedirs(base_path)

    # Fake data
    modules_meta = [{
        "id": 1,
        "name": "Module 1",
        "position": 1,
        "items": [{"id": 11, "type": "Assignment", "content_id": 201, "title": "Essay"}]
    }]
    assignments_meta = [{"id": 201, "name": "Essay 1"}]
    discussions_meta = []
    pages_meta = []

    # Write fake metadata
    with open(base_path / "modules_metadata.json", "w") as f:
        json.dump(modules_meta, f)
    with open(base_path / "assignments_metadata.json", "w") as f:
        json.dump(assignments_meta, f)
    with open(base_path / "discussions_metadata.json", "w") as f:
        json.dump(discussions_meta, f)
    with open(base_path / "pages_metadata.json", "w") as f:
        json.dump(pages_meta, f)

    result = combine_metadata(course_id, output_dir=str(tmp_output))

    assert result[0]["items"][0]["metadata"]["name"] == "Essay 1"
