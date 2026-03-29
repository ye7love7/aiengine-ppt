from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


TaskStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TaskStage = Literal[
    "queued",
    "ingest",
    "strategist",
    "executor_svg",
    "executor_notes",
    "postprocess",
    "export",
    "completed",
    "failed",
    "cancelled",
]
SourceMode = Literal["path", "upload"]
PreferStyle = Literal["general", "consulting", "consulting_top", "auto"]
OutputFormat = Literal["native_pptx", "svg_pptx"]


class TaskCreateRequest(BaseModel):
    source_mode: SourceMode
    project_name: str = Field(min_length=1, max_length=120)
    canvas_format: str = "ppt169"
    template_name: Optional[str] = None
    example_reference: Optional[str] = None
    audience: Optional[str] = None
    use_case: Optional[str] = None
    core_message: Optional[str] = None
    prefer_style: PreferStyle = "auto"
    notes_style: str = "formal"
    output_formats: list[OutputFormat] = Field(default_factory=lambda: ["native_pptx", "svg_pptx"])
    source_files: list[str] = Field(default_factory=list)
    image_files: list[str] = Field(default_factory=list)


class ArtifactEntry(BaseModel):
    name: str
    kind: Literal["file", "directory", "log"]
    relative_path: str
    size_bytes: Optional[int] = None


class TaskState(BaseModel):
    task_id: str
    status: TaskStatus
    stage: TaskStage
    created_at: datetime
    updated_at: datetime
    request: dict[str, Any]
    upstream_user_id: Optional[str] = None
    project_path: Optional[str] = None
    log_path: Optional[str] = None
    error: Optional[str] = None
    cancel_requested: bool = False
    artifacts: list[ArtifactEntry] = Field(default_factory=list)
    stage_details: dict[str, Any] = Field(default_factory=dict)


class TaskCreateResponse(BaseModel):
    task_id: str
    status: TaskStatus
    stage: TaskStage
