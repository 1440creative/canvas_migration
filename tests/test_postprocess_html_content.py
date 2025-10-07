import json
from pathlib import Path

from importers.import_course import _postprocess_html_content
from tests.conftest import DummyCanvas


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_postprocess_rewrites_assignment_and_discussion(tmp_path):
    export_root = tmp_path / "123"
    course_meta = export_root / "course" / "course_metadata.json"
    _write(course_meta, json.dumps({"id": 123}))

    # Assignment HTML that references the legacy syllabus URL
    assignment_dir = export_root / "assignments" / "001_assignment"
    assignment_html = assignment_dir / "index.html"
    _write(
        assignment_dir / "assignment_metadata.json",
        json.dumps(
            {
                "id": 11,
                "html_path": str(assignment_html.relative_to(export_root)),
            }
        ),
    )
    _write(
        assignment_html,
        '<a href="https://canvas.test/courses/123/assignments/syllabus">See syllabus</a>',
    )

    # Discussion HTML that references a legacy file link
    discussion_dir = export_root / "discussions" / "001_discussion"
    discussion_html = discussion_dir / "index.html"
    _write(
        discussion_dir / "discussion_metadata.json",
        json.dumps(
            {
                "id": 31,
                "html_path": str(discussion_html.relative_to(export_root)),
            }
        ),
    )
    _write(
        discussion_html,
        '<a href="/courses/123/files/45/download">Download</a>',
    )

    id_map = {
        "assignments": {11: 21},
        "discussions": {31: 41},
        "files": {45: 99},
    }

    canvas = DummyCanvas(api_base="https://canvas.test")

    _postprocess_html_content(
        canvas=canvas,
        export_root=export_root,
        target_course_id=456,
        id_map=id_map,
    )

    assign_call = next(
        call for call in canvas.put_calls if "/courses/456/assignments/21" in call["endpoint"]
    )
    assignment_body = assign_call["json"]["assignment"]["description"]
    assert 'courses/456/assignments/syllabus' in assignment_body

    discussion_call = next(
        call for call in canvas.put_calls if "/courses/456/discussion_topics/41" in call["endpoint"]
    )
    discussion_body = discussion_call["json"]["discussion_topic"]["message"]
    assert '/courses/456/files/99' in discussion_body
