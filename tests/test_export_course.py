# tests/test_export_course.py

import pytest
from unittest.mock import patch
from export.export_course import export_course

@patch("export.export_course.export_pages")
@patch("export.export_course.export_modules")
@patch("export.export_course.export_assignment_groups")
@patch("export.export_course.export_assignments")
@patch("export.export_course.export_quizzes")
@patch("export.export_course.export_discussions")
@patch("export.export_course.export_files")
@patch("export.export_course.export_course_settings")
@patch("export.export_course.export_blueprint_settings")
def test_export_course_calls_all_exports(
    mock_blueprint,
    mock_settings,
    mock_files,
    mock_discussions,
    mock_quizzes,
    mock_assignments,
    mock_assignment_groups,
    mock_modules,
    mock_pages,
    tmp_path,
):
    course_id = 123

    api_sentinel = object()
    export_course(course_id, tmp_path, api=api_sentinel)

    course_output_dir = tmp_path / str(course_id)

    mock_pages.assert_called_once_with(course_id, tmp_path, api_sentinel)
    mock_modules.assert_called_once_with(course_id, tmp_path, api_sentinel)
    mock_assignments.assert_called_once_with(course_id, tmp_path, api_sentinel)
    mock_assignment_groups.assert_called_once_with(course_id, tmp_path, api_sentinel)
    mock_quizzes.assert_called_once_with(course_id, tmp_path, api_sentinel)
    mock_discussions.assert_called_once_with(course_id, tmp_path, api_sentinel)
    mock_files.assert_called_once_with(course_id, tmp_path, api_sentinel)
    mock_settings.assert_called_once_with(course_id, tmp_path, api_sentinel)
    mock_blueprint.assert_called_once_with(course_id, tmp_path, api_sentinel)
