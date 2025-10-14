from __future__ import annotations

from pathlib import Path

from utils.html_postprocessor import postprocess_html


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_postprocess_html_rewrites_links(tmp_path):
    export_root = tmp_path / "77275"
    html_path = export_root / "pages" / "home" / "index.html"
    course_meta = export_root / "course" / "course_metadata.json"

    _write(course_meta, '{"id": 77275}')

    _write(
        html_path,
        """
        <a href="https://canvas.example.com/courses/77275/files/45/download">File</a>
        <a href="https://canvas.example.com/api/v1/courses/77275/discussion_topics/77">Discussion</a>
        <a href="/courses/77275/modules/88">Module</a>
        <a href="https://canvas.example.com/courses/77275/modules">Modules index</a>
        <a data-api-endpoint="https://canvas.example.com/api/v1/courses/77275/modules">Modules API</a>
        <a href="/courses/77275/announcements">Announcements</a>
        <a data-api-endpoint="/api/v1/courses/77275/announcements">Announcements API</a>
        """,
    )

    id_map = {
        "files": {45: 900},
        "discussions": {77: 910},
        "modules": {88: 920},
    }

    report = postprocess_html(
        export_root=export_root,
        target_course_id=456,
        id_map=id_map,
    )

    assert report.rewrites_applied == 1
    updated_html = html_path.read_text(encoding="utf-8")
    assert "courses/456/files/900" in updated_html
    assert "courses/456/discussion_topics/910" in updated_html
    assert "courses/456/modules/920" in updated_html
    assert 'courses/456/modules"' in updated_html
    assert 'api/v1/courses/456/modules' in updated_html
    assert 'courses/456/announcements' in updated_html
    assert 'api/v1/courses/456/announcements' in updated_html


def test_postprocess_html_dry_run(tmp_path):
    export_root = tmp_path / "12345"
    html_path = export_root / "pages" / "a" / "body.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text("<a href=\"/courses/12345/files/7\">File</a>", encoding="utf-8")

    id_map = {"files": {7: 99}}

    report = postprocess_html(
        export_root=export_root,
        target_course_id=555,
        id_map=id_map,
        dry_run=True,
    )

    assert report.rewrites_applied == 1
    assert html_path.read_text(encoding="utf-8") == "<a href=\"/courses/12345/files/7\">File</a>"


def test_postprocess_html_no_changes(tmp_path):
    export_root = tmp_path / "98765"
    html_path = export_root / "pages" / "b" / "index.html"
    _write(html_path, "<p>No Canvas links here</p>")

    id_map = {"files": {}}

    report = postprocess_html(
        export_root=export_root,
        target_course_id=555,
        id_map=id_map,
    )

    assert report.rewrites_applied == 0
    assert html_path.read_text(encoding="utf-8") == "<p>No Canvas links here</p>"
