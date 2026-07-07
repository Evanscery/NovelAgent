"""Pydantic request/response models for the API layer.

These schemas are the wire contract for ``/api/projects`` and the routes
added in todos 22-23. Project ids are **always** system-controlled
(refactor_guide:39), so create requests carry only ``display_name`` and
``mode`` — the id is generated server-side and returned in the response.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "CreateProjectRequest",
    "PatchProjectRequest",
    "ProjectListResponse",
    "ProjectResponse",
    "ProjectSummary",
]

_VALID_MODES = {"novel", "rp"}


class CreateProjectRequest(BaseModel):
    """POST /api/projects body."""

    display_name: str = Field(..., min_length=1, description="Human-readable project name")
    mode: str = Field(default="novel", description="novel or rp")


class PatchProjectRequest(BaseModel):
    """PATCH /api/projects/{id} body — partial update of project config.yaml."""

    display_name: str | None = Field(default=None, min_length=1)
    mode: str | None = Field(default=None)

    def has_updates(self) -> bool:
        return self.display_name is not None or self.mode is not None


class ProjectSummary(BaseModel):
    """Lightweight project entry for list responses."""

    id: str
    display_name: str
    mode: str


class ProjectResponse(BaseModel):
    """Full project response (create / detail)."""

    id: str
    display_name: str
    mode: str
    path: str


class ProjectListResponse(BaseModel):
    """GET /api/projects response."""

    projects: list[ProjectSummary]
