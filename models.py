#models.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Literal

from utils.dates import normalize_iso8601

Artifact = Literal["course", "pages", "modules", "assignments", "files", "quizzes", "discussions"]

@dataclass(frozen=True, slots=True)
class PageMeta:
    id: Optional[int]
    url: Optional[str]
    title: Optional[str]
    position: Optional[int] = None# Export-only reference; ignored by import. Use ModuleItemMeta.position.
    module_item_ids: List[int] = field(default_factory=list)
    published: bool = True
    updated_at: Optional[str] = None  # Expected ISO-8601; normalized on init
    html_path: Optional[str] = None # relative to export/data/{course_id}
    source_api_url: Optional[str] = None
    front_page: bool = False 
    
    def __post_init__(self):
        object.__setattr__(self, "updated_at", normalize_iso8601(self.updated_at) or self.updated_at)
    
ModuleItemType = Literal[
    "File",
    "Page",
    "Discussion",
    "Assignment",
    "Quiz",
    "SubHeader",
    "ExternalUrl",
    "ExternalTool",
]
@dataclass(frozen=True, slots=True)
class ModuleItemMeta:
    id: int
    position: int
    type: ModuleItemType
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
    
    def __post_init__(self):
        object.__setattr__(self, "updated_at", normalize_iso8601(self.updated_at) or self.updated_at)


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
    
    def __post_init__(self):
        object.__setattr__(self, "updated_at", normalize_iso8601(self.updated_at) or self.updated_at)
        object.__setattr__(self, "due_at", normalize_iso8601(self.due_at))

@dataclass(frozen=True, slots=True)
class DiscussionMeta:
    id: int
    title: str
    published: bool
    html_path: Optional[str]
    updated_at: str
    module_item_ids: List[int]
    source_api_url: str

@dataclass(frozen=True, slots=True)
class FileMeta:
    id: int
    filename: str
    content_type: Optional[str]
    folder_path: str  # Canvas virtual folder path (NOT local). Missing segments are auto-created on upload.
    md5: Optional[str]      # Sidecar hash from export (if available)
    sha256: Optional[str]   # Prefer this for identity/skip logic
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
    quizzes: List[QuizMeta] = field(default_factory=list)
    discussions: List[DiscussionMeta] = field(default_factory=list) 

@dataclass(frozen=True, slots=True)
class QuizMeta:
    id: int
    title: str
    quiz_type: str                  # "assignment", "practice_quiz", "graded_survey", "survey"
    published: bool
    points_possible: Optional[float]
    time_limit: Optional[int]
    allowed_attempts: Optional[int]
    shuffle_answers: Optional[bool]
    scoring_policy: Optional[str]   # "keep_highest", "keep_latest"
    one_question_at_a_time: Optional[bool]
    due_at: Optional[str]
    unlock_at: Optional[str]
    lock_at: Optional[str]
    html_path: Optional[str]        # exported relative path to description HTML
    updated_at: str
    module_item_ids: List[int]
    source_api_url: str
    
    def __post_init__(self):
        object.__setattr__(self, "updated_at", normalize_iso8601(self.updated_at) or self.updated_at)
        object.__setattr__(self, "due_at", normalize_iso8601(self.due_at))
        object.__setattr__(self, "unlock_at", normalize_iso8601(self.unlock_at))
        object.__setattr__(self, "lock_at", normalize_iso8601(self.lock_at))
        

