# tests/test_models_datetime_normalization.py
from models import PageMeta, ModuleMeta, AssignmentMeta, QuizMeta, ModuleItemMeta
from typing import List


def _dummy_items() -> List[ModuleItemMeta]:
    return [ModuleItemMeta(id=1, position=1, type="SubHeader", content_id=None, title="T", url=None)]


def test_page_meta_normalizes_updated_at_zulu():
    p = PageMeta(
        id=1, url="welcome", title="Welcome", position=1, module_item_ids=[],
        published=True, updated_at="2025-08-19T10:52:51-07:00",
        html_path="pages/001_welcome/index.html", source_api_url="x"
    )
    assert p.updated_at == "2025-08-19T17:52:51Z"


def test_module_meta_normalizes_updated_at_fractional():
    m = ModuleMeta(
        id=7, name="Week 1", position=1, published=True, items=_dummy_items(),
        updated_at="2025-08-19T17:52:51.123456Z", source_api_url="x"
    )
    assert m.updated_at == "2025-08-19T17:52:51Z"


def test_assignment_meta_normalizes_due_and_updated():
    a = AssignmentMeta(
        id=42, name="HW", position=1, published=True,
        due_at="2025-09-01T23:59:00-07:00", points_possible=10.0,
        html_path=None, updated_at="2025-08-10T12:00:00Z",
        module_item_ids=[], source_api_url="x"
    )
    assert a.updated_at == "2025-08-10T12:00:00Z"
    assert a.due_at == "2025-09-02T06:59:00Z"  # converted to UTC


def test_quiz_meta_normalizes_all_times():
    q = QuizMeta(
        id=99, title="Quiz", quiz_type="assignment", published=True,
        points_possible=None, time_limit=None, allowed_attempts=None,
        shuffle_answers=None, scoring_policy=None, one_question_at_a_time=None,
        due_at="2025-12-01T12:00:00+02:00",
        unlock_at="2025-11-01T00:00:00Z",
        lock_at="2025-12-15T23:59:59.999Z",
        html_path=None, updated_at="2025-10-10T10:10:10-05:00",
        module_item_ids=[], source_api_url="x"
    )
    assert q.updated_at == "2025-10-10T15:10:10Z"
    assert q.unlock_at == "2025-11-01T00:00:00Z"
    assert q.due_at == "2025-12-01T10:00:00Z"
    assert q.lock_at == "2025-12-15T23:59:59Z"  # microseconds stripped
