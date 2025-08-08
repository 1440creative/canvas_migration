from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Literal

Artifact = Literal["course", "page", "modules", "assignments", "files", "quizzes", "discussions"]

@dataclass(frozen=True, slots=True)
class PageMeta:
    id: int
    url: str
    title: str
    position: int
    module_item_ids: List[int]
    published: bool
    updated_at: str
    html_path: str  # relative to export/data/{course_id}
    source_api_url: str
    
@dataclass(frozen=True, slots=True)
class ModuleItemMeta:
    id: int
    position: int
    type: str   # "Page", "Assignment", "File", "Quiz", "Discussion"
    content_id: Optional[int]
    title: str
    url: Optional[str] # slug or web url if applicable
    
@dataclass(frozen=True, slots=True)
class ModuleMeta:
    id: int
    name: str
    position: int
    published: bool
    items: List[ModuleItemMeta]
    updated_at: str
    source_api_url: str

@dataclass(frozen=True, slots=True)
class AssignmentMeta:
    id: int
    name: str
    position: int
    published: bool
    due_at: Optional[str]
    points_possible: Optional[float]
    html_path: Optional[str]
    updated_at: str
    module_item_ids: List[int]
    source_api_url: str

@dataclass(frozen=True, slots=True)
class FileMeta:
    id: int
    filename: str
    content_type: Optional[str]
    md5: Optional[str]
    sha256: Optional[str]
    folder_path: str    # Canvas folder path
    file_path: str      # exported relative path
    module_item_ids: List[int]
    source_api_url: str
    
@dataclass(frozen=True, slots=True)
class CourseMeta:
    id: int
    name: str
    course_code: str
    workflow_state: str
    settings: Dict[str, object] = field(default_factory=dict)
    exported_root: str = ""
    source_api_url: str = ""

@dataclass(frozen=True, slots=True)
class CourseStructure:
    course: CourseMeta
    pages: List[PageMeta] = field(default_factory=list)
    modules: List[ModuleMeta] = field(default_factory=list)
    assignments: List[AssignmentMeta] = field(default_factory=list)
    files: List[FileMeta] = field(default_factory=list)    