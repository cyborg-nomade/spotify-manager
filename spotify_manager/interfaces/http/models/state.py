"""Stable state HTTP request/response contracts."""

from typing import Any

from pydantic import BaseModel


class SharedStateSnapshot(BaseModel):
    """One revision-guarded snapshot of the complete shared state."""

    revision: str
    document: dict[str, Any]


class SharedStateReplaceRequest(BaseModel):
    """Guarded manual replacement of the complete shared state."""

    expected_revision: str
    document: dict[str, Any]


class SharedStateNamespaceReplaceRequest(BaseModel):
    """Guarded manual replacement of one validated state namespace."""

    expected_revision: str
    value: dict[str, Any]


class SharedStateSummary(BaseModel):
    """Compact metadata for the cockpit state indicator."""

    revision: str
    updated_at: str
    namespaces: dict[str, str]
