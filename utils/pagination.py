# utils/pagination.py
from __future__ import annotations
from typing import Any, Dict, List, Union

from utils.api import CanvasAPI

Json = Union[Dict[str, Any], List[Dict[str, Any]]]

def get_list(api: CanvasAPI, endpoint: str) -> List[Dict[str, Any]]:
    """
    Thin wrapper that defers pagination to CanvasAPI.get().
    Returns a list (empty if server returned an object by mistake).
    Accepts endpoints with or without '/api/v1' prefix.
    """
    data = api.get(endpoint)
    return data if isinstance(data, list) else []

def get_object(api: CanvasAPI, endpoint: str) -> Dict[str, Any]:
    """
    Return a single JSON object, or {} if server returned a list.
    """
    data = api.get(endpoint)
    return data if isinstance(data, dict) else {}

# Convenience helpers (optional—use if you like the readability)
def list_modules(api: CanvasAPI, course_id: int) -> List[Dict[str, Any]]:
    return get_list(api, f"/courses/{course_id}/modules")

def list_module_items(api: CanvasAPI, course_id: int, module_id: int) -> List[Dict[str, Any]]:
    return get_list(api, f"/courses/{course_id}/modules/{module_id}/items")

def list_assignments(api: CanvasAPI, course_id: int) -> List[Dict[str, Any]]:
    return get_list(api, f"/courses/{course_id}/assignments")

def list_quizzes(api: CanvasAPI, course_id: int) -> List[Dict[str, Any]]:
    return get_list(api, f"/courses/{course_id}/quizzes")

def list_discussions(api: CanvasAPI, course_id: int) -> List[Dict[str, Any]]:
    return get_list(api, f"/courses/{course_id}/discussion_topics")

def get_course(api: CanvasAPI, course_id: int) -> Dict[str, Any]:
    return get_object(api, f"/courses/{course_id}")
