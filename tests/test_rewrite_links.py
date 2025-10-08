import textwrap

from importers.import_course import rewrite_canvas_links


def test_rewrite_canvas_links_numeric_and_pages():
    html = textwrap.dedent(
        """
        <a href="https://canvas.test/courses/123/files/45/download">File</a>
        <a data-api-endpoint="https://canvas.test/api/v1/courses/123/files/45">Data</a>
        <img src="/api/v1/files/45/preview">
        <a href="https://canvas.test/courses/123/assignments/55">Assignment</a>
        <a href="https://canvas.test/api/v1/courses/123/quizzes/66">Quiz</a>
        <a href="/courses/123/discussion_topics/77">Discussion</a>
        <a href="https://canvas.test/courses/123/pages/home-page">Page</a>
        <a href="https://canvas.test/api/v1/courses/123/pages/home-page">Page API</a>
        <a href="/courses/123/modules/88">Module</a>
        """
    )

    id_map = {
        "files": {45: 900},
        "assignments": {55: 910},
        "quizzes": {66: 920},
        "discussions": {77: 930},
        "modules": {88: 940},
        "pages_url": {"home-page": "welcome"},
    }

    rewritten = rewrite_canvas_links(
        html,
        source_course_id=123,
        target_course_id=456,
        id_map=id_map,
    )

    assert "courses/456/files/900" in rewritten
    assert "api/v1/courses/456/files/900" in rewritten
    assert "api/v1/files/900" in rewritten
    assert "courses/456/assignments/910" in rewritten
    assert "api/v1/courses/456/quizzes/920" in rewritten
    assert "courses/456/discussion_topics/930" in rewritten
    assert "courses/456/pages/welcome" in rewritten
    assert "api/v1/courses/456/pages/welcome" in rewritten
    assert "courses/456/modules/940" in rewritten


def test_rewrite_canvas_links_strips_source_host():
    html = textwrap.dedent(
        """
        <img src="https://canvas.test/courses/123/files/45/preview">
        <a data-api-endpoint="https://canvas.test/api/v1/courses/123/files/45">Data</a>
        <a href="https://canvas.test/files/45/download">Download</a>
        """
    )

    rewritten = rewrite_canvas_links(
        html,
        source_course_id=123,
        target_course_id=456,
        id_map={"files": {45: 900}},
    )

    assert "https://canvas.test" not in rewritten
    assert 'src="/courses/456/files/900/preview"' in rewritten
    assert 'data-api-endpoint="/api/v1/courses/456/files/900"' in rewritten
    assert 'href="/files/900/download"' in rewritten


def test_rewrite_canvas_links_missing_mapping_no_change():
    html = '<a href="https://canvas.test/courses/123/files/45">File</a>'
    id_map = {"files": {}}  # no mapping available

    rewritten = rewrite_canvas_links(
        html,
        source_course_id=123,
        target_course_id=456,
        id_map=id_map,
    )

    assert rewritten == html


def test_rewrite_canvas_links_syllabus_slug():
    html = (
        '<a href="https://canvas.test/courses/123/assignments/syllabus">Syllabus</a>'
        '<a href="/courses/123/assignments/syllabus#summary">Anchor</a>'
        '<a href="https://canvas.test/api/v1/courses/123/assignments/syllabus?module_item_id=10">API</a>'
    )

    rewritten = rewrite_canvas_links(
        html,
        source_course_id=123,
        target_course_id=789,
        id_map={},
    )

    assert 'courses/789/assignments/syllabus"' in rewritten
    assert '/courses/789/assignments/syllabus#summary' in rewritten
    assert '/api/v1/courses/789/assignments/syllabus?module_item_id=10' in rewritten
    assert "https://canvas.test" not in rewritten
