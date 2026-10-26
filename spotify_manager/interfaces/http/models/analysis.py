"""Stable analysis HTTP request/response contracts."""

from pydantic import BaseModel
from pydantic import Field

from spotify_manager.interfaces.operations import analyse_library as library_analysis

from .common import JobStatus


class AnalysisResourceProgress(BaseModel):
    """Latest progress for one library resource."""

    completed: int = 0
    total: int | None = None
    status: str = "Queued"


class AnalysisJobLog(BaseModel):
    """One timestamped analysis event shown by the web interface."""

    sequence: int
    timestamp: str
    message: str


class AnalysisJobResult(BaseModel):
    """Pollable state for one background library analysis."""

    job_id: str
    command: str
    status: JobStatus = "queued"
    detail: str | None = None
    retry_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    run_id: str | None = None
    backup_dir: str | None = None
    full_rebuild: bool = False
    mirror_resource: library_analysis.ResourceName | None = None
    resources: dict[str, AnalysisResourceProgress]
    logs: list[AnalysisJobLog] = Field(default_factory=list)
