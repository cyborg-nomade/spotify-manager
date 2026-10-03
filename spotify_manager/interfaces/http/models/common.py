"""Stable common HTTP request/response contracts."""

from typing import Literal

from pydantic import BaseModel


class CommandResult(BaseModel):
    """Result of running a side-effecting command endpoint."""

    command: str
    status: str = "completed"
    detail: str | None = None


class CountResult(BaseModel):
    """Number of artists in the YourLibrary file."""

    count: int


JobStatus = Literal[
    "queued",
    "running",
    "waiting",
    "cancelling",
    "cancelled",
    "paused",
    "completed",
    "failed",
]


class ServerFileStatus(BaseModel):
    """Filesystem update status for one canonical server-side mirror."""

    filename: str
    exists: bool
    updated_at: str | None = None


class LibraryMirrorFilesStatus(BaseModel):
    """Update status for the files consumed by New Wine."""

    files: list[ServerFileStatus]
