"""Pydantic request/response models for the API layer.

These schemas are the wire contract for ``/api/projects`` and the routes
added in todos 22-23. Project ids are **always** system-controlled
(refactor_guide:39), so create requests carry only ``display_name`` and
``mode`` — the id is generated server-side and returned in the response.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "AgentConfigResponse",
    "ChatMessage",
    "ChatMessageRole",
    "ChatResponse",
    "ConfigResponse",
    "CreateProjectRequest",
    "ImportRequest",
    "ImportResponse",
    "NovelChapterListResponse",
    "NovelChapterResponse",
    "NovelChapterSummary",
    "PatchProjectRequest",
    "ProjectListResponse",
    "ProjectResponse",
    "ProjectSummary",
    "PutAgentConfigRequest",
    "PutGlobalConfigRequest",
    "PutProjectConfigRequest",
    "PutResourceRequest",
    "ResourceContentResponse",
    "ResourceHistoryEntry",
    "ResourceHistoryResponse",
    "ResourceListEntry",
    "ResourceListResponse",
    "RetryResponse",
    "RoundResultSummary",
    "RoundState",
    "RoundStatusResponse",
    "RunWorkflowRequest",
    "SendChatRequest",
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


# ── Workflow run routes (todo 22) ────────────────────────────────────────


ChatMessageRole = Literal["user", "director", "system"]


class RunWorkflowRequest(BaseModel):
    """POST /api/workflow/{project_id}/run body.

    All fields optional; defaults come from the project's workflow.yaml and
    the global runtime config.
    """

    context: str = Field(default="", description="Extra context injected into the director prompt")
    max_iterations: int | None = Field(default=None, gt=0, description="Override budget max_iterations")
    maximal_recursive_calling_depth: int = Field(
        default=1, ge=0, description="Max cur_depth - target_depth for recursive calls"
    )


class RoundResultSummary(BaseModel):
    """Summary of a completed :class:`~app.agents.director.RoundResult`."""

    completed_agents: list[str] = Field(default_factory=list)
    finalize_reason: str = ""
    total_tokens: int = 0
    recursive_calls: list[dict[str, object]] = Field(default_factory=list)
    rejected_calls: list[dict[str, object]] = Field(default_factory=list)


RoundState = Literal["pending", "running", "completed", "failed"]


class RoundStatusResponse(BaseModel):
    """GET /api/workflow/{project_id}/round/{round_id} response."""

    round_id: str
    state: RoundState
    logs: list[str] = Field(default_factory=list)
    result: RoundResultSummary | None = None
    error: str | None = None


# ── Chat routes (todo 22) ────────────────────────────────────────────────


class ChatMessage(BaseModel):
    """A single chat message in the director chat log."""

    message_id: str = Field(description="Stable unique id (e.g. ``msg_<uuid8>``)")
    role: ChatMessageRole
    content: str
    turn_id: str = Field(description="The Turn commit this message belongs to / produced")
    timestamp: str = Field(description="ISO-8601 UTC timestamp")


class SendChatRequest(BaseModel):
    """POST /api/chat/{project_id} body."""

    content: str = Field(..., min_length=1, description="User message text")


class ChatResponse(BaseModel):
    """POST /api/chat/{project_id} response — the appended user message +
    the director's reply (if produced synchronously)."""

    user_message: ChatMessage
    director_message: ChatMessage | None = None


class RetryResponse(BaseModel):
    """POST /api/chat/{project_id}/{message_id}/retry response.

    The retried user message is re-sent after rollback; the director
    produces a fresh reply. The new branch name (from
    :meth:`VersionManager.rollback`) is returned so the client can show
    that a new timeline was created.
    """

    branch: str = Field(description="New git branch created by the rollback")
    user_message: ChatMessage
    director_message: ChatMessage | None = None


# ── Resource routes (todo 23) ───────────────────────────────────────────


class ResourceListEntry(BaseModel):
    """One resource type in a ``GET /api/resources/{project_id}`` response.

    The ``content_summary`` is a short preview derived from the
    resource's working-tree content (first non-empty chunk, truncated).
    """

    type: str = Field(description="Resource type key (e.g. ``outline``)")
    title: str = Field(description="Human-readable Chinese title (e.g. ``大纲``)")
    exists: bool = Field(description="True if the resource directory is non-empty")
    file_count: int = Field(default=0, description="Number of content files (excl. metadata)")
    content_summary: str = Field(default="", description="Truncated preview of the content")


class ResourceListResponse(BaseModel):
    """GET /api/resources/{project_id} response.

    The ``resources`` list ALWAYS contains one entry per registered
    resource type (8 types) — even when the project has not yet written
    any content to a type, so the front-end can render all editor tabs.
    """

    project_id: str
    resources: list[ResourceListEntry]


class PutResourceRequest(BaseModel):
    """PUT /api/resources/{project_id}/{type} body.

    Either ``content`` (whole-resource overwrite) or ``filename`` +
    ``content`` (write a single file). When ``filename`` is omitted the
    content is written to ``content.md`` (the canonical default file).
    """

    content: str = Field(..., min_length=1, description="New file content")
    filename: str | None = Field(
        default=None, description="Target filename within the resource; default ``content.md``"
    )


class ResourceContentResponse(BaseModel):
    """GET /api/resources/{project_id}/{type} response (full content)."""

    project_id: str
    type: str
    title: str
    read_only: bool = Field(description="True for the ``variables`` type (front-end display only)")
    content: str
    files: list[str] = Field(default_factory=list, description="Content filenames in this resource")


class ResourceHistoryEntry(BaseModel):
    """One commit in a resource's version history."""

    sha: str
    turn_id: str
    message: str
    timestamp: str = Field(description="ISO-8601 UTC timestamp")
    branch: str


class ResourceHistoryResponse(BaseModel):
    """GET /api/resources/{project_id}/{type}/history response."""

    project_id: str
    type: str
    commits: list[ResourceHistoryEntry]


# ── Config routes (todo 23) ─────────────────────────────────────────────


class ConfigResponse(BaseModel):
    """GET /api/config and GET /api/config/{project_id} response.

    For the global endpoint ``project_id`` is empty. The ``models`` /
    ``runtime`` / ``server`` blobs are the raw layer dicts (not the
    parsed pydantic models) so the front-end can render and edit the
    exact yaml structure without a schema round-trip.
    """

    project_id: str = ""
    display_name: str | None = None
    mode: str | None = None
    models: dict[str, object] = Field(default_factory=dict)
    runtime: dict[str, object] = Field(default_factory=dict)
    server: dict[str, object] = Field(default_factory=dict)


class PutGlobalConfigRequest(BaseModel):
    """PUT /api/config body — replace one or more global tier files.

    Each top-level key is optional; only the provided blobs are written
    back to ``config/<name>.yaml`` (the others are left untouched).
    """

    models: dict[str, object] | None = None
    runtime: dict[str, object] | None = None
    server: dict[str, object] | None = None


class PutProjectConfigRequest(BaseModel):
    """PUT /api/config/{project_id} body.

    ``display_name`` / ``mode`` update the project's ``config.yaml``
    top-level fields; any of the optional blobs (``models`` / ``runtime``
    / ``server``) are written as per-project overrides in the same
    ``config.yaml`` (deep-merged with global on read by
    :class:`~app.config_loader.ConfigLoader`).
    """

    display_name: str | None = Field(default=None, min_length=1)
    mode: str | None = None
    models: dict[str, object] | None = None
    runtime: dict[str, object] | None = None
    server: dict[str, object] | None = None

    def has_updates(self) -> bool:
        return any(
            v is not None
            for v in (
                self.display_name,
                self.mode,
                self.models,
                self.runtime,
                self.server,
            )
        )


class AgentConfigResponse(BaseModel):
    """One agent's attribute set (per refactor_guide:62-73 + todo 18).

    ``allow_recursive`` is included because it is serializable to yaml
    and the front-end config page exposes it as a per-agent toggle
    (todo 18 / plan scope).
    """

    name: str
    task: str
    input: str
    output: str
    permission: dict[str, list[str]]
    model: str | None = None
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    head: str | None = None
    tail: str | None = None
    allow_recursive: bool = True


class PutAgentConfigRequest(BaseModel):
    """PUT /api/config/{project_id}/agents/{name} body.

    Every editable attribute from refactor_guide:368-384 is accepted.
    The ``name`` path parameter is authoritative — a body ``name``
    mismatch is rejected with 400 by the route handler.
    """

    name: str = Field(..., min_length=1)
    task: str = Field(..., min_length=1)
    input: str = Field(..., min_length=1)
    output: str = Field(..., min_length=1)
    permission: dict[str, list[str]] = Field(..., description="Hash<string, vector> per guide:77-80")
    model: str | None = None
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    head: str | None = None
    tail: str | None = None
    allow_recursive: bool = True


# ── Novel routes (todo 23) ──────────────────────────────────────────────


class NovelChapterSummary(BaseModel):
    """One chapter entry in a chapter list response."""

    filename: str = Field(description="e.g. ``chapter_01.txt``")
    chapter_number: int | None = Field(
        default=None, description="Numeric chapter parsed from filename, if any"
    )
    size_bytes: int


class NovelChapterListResponse(BaseModel):
    """GET /api/novel/{project_id} response."""

    project_id: str
    chapters: list[NovelChapterSummary]


class NovelChapterResponse(BaseModel):
    """GET /api/novel/{project_id}/{chapter} response."""

    project_id: str
    filename: str
    chapter_number: int | None = None
    content: str


# ── Import route (todo 34 — compat layer delegation) ─────────────────────


class ImportRequest(BaseModel):
    """POST /api/import body — card import via the compat layer.

    Two modes:

    * **Card file path** — ``source`` is a path to a card file on disk
      (``.json`` for a v2/v3 character card). The handler loads it,
      infers a :class:`~app.compat.tavern_card.card_migration.CardIR`,
      scaffolds a new project (or reuses ``project_id`` if given), and
      materializes the 8 resources from the card.
    * **Inline card payload** — ``card`` is the parsed card dict directly
      (useful from a front-end that has already read the file). Same
      pipeline as above starting at :func:`infer_card_ir`.

    ``display_name`` overrides the project's display name (defaults to the
    card's name). ``mode`` overrides the runtime plan's recommendation
    (defaults to the plan's ``recommended_mode``).
    """

    source: str | None = Field(default=None, description="Path to a card file on disk")
    card: dict[str, object] | None = Field(
        default=None, description="Inline card payload (alternative to ``source``)"
    )
    project_id: str | None = Field(
        default=None, description="Target an existing project id (optional)"
    )
    display_name: str | None = Field(
        default=None, description="Override project display name (defaults to card name)"
    )
    mode: str | None = Field(
        default=None, description="Override mode (novel/rp); defaults to plan recommendation"
    )


class ImportResponse(BaseModel):
    """POST /api/import success response (201)."""

    project_id: str
    display_name: str
    mode: str
    resources_created: list[str] = Field(
        default_factory=list,
        description="Resource types that received card-derived content",
    )
    front_scripts_written: int = Field(
        default=0, description="Number of front scripts copied to front/"
    )
    paths: dict[str, str] = Field(
        default_factory=dict, description="Logical name -> file path written"
    )
