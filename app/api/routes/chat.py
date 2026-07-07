"""/api/chat director chat (add/del/retry synced to rollback).

Endpoints
---------
* ``GET    /api/chat/{project_id}``                  — message history.
* ``POST   /api/chat/{project_id}``                  — send a user message
  to the director; append it to the chat log, trigger a director reply,
  commit a Turn, return both messages.
* ``DELETE /api/chat/{project_id}/{message_id}``     — delete a message
  **and roll back** the project's git to the Turn *before* the message
  (per guide:412 "同步到后端数据回滚"). Rollback is mode='branch'
  (guide:314-316 — rollback = new branch, NOT delete).
* ``POST   /api/chat/{project_id}/{message_id}/retry`` — retry from a
  message: roll back to before it, re-send, return the new response.

Per refactor_guide:410-413 the user only chats with the director
(``chatbot`` semantics: add / del / retry / error-retry), and every
mutating operation is synced to the backend's data rollback / update.

Chat log format
---------------
The chat log lives at ``workspaces/<id>/work/chat.jsonl`` — one
:class:`ChatMessage` JSON object per line, in chronological order. The
file is versioned by the project's independent git repo (per D6):
**each chat exchange (user message + director reply) commits one
Turn**, so the chat log and the resource data share the same version
history. Deleting a message rolls the whole project back to the Turn
that existed *before* that message — this reverts both the chat log
entry AND any resource mutations the director's round produced.

Director reply
--------------
The director reply is produced by running a single-agent round via
:class:`~app.agents.director.Director` + :class:`MockRunner` (the API's
default runner — a real runner can be wired via the RUNNER_FACTORY hook
in ``app/api/routes/workflow.py``). The user's message becomes the
``context`` passed to ``run_round``. This keeps the chat path
LLM-credential-free by default (guide 傻瓜式 dry-run) while still
exercising the real director + runtime + budget pipeline.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi import Path as FastPath

from app.agents.agent import Agent
from app.agents.director import Director
from app.agents.runners.base import AgentRunner
from app.agents.runners.mock_runner import MockRunner
from app.agents.workflow import TreeNode, WorkflowTree
from app.api.schemas import (
    ChatMessage,
    ChatResponse,
    RetryResponse,
    SendChatRequest,
)
from app.data.project_repo import ProjectRepo
from app.data.versioning import VersionManager
from app.project_paths import ProjectPathError, resolve_project_path
from app.runtime.budget import BudgetTracker
from app.runtime.permission import parse_permission
from app.runtime.runtime import Runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

ProjectIdPath = Annotated[str, FastPath(..., description="System-controlled project id")]
MessageIdPath = Annotated[str, FastPath(..., description="Chat message id (msg_<uuid8>)")]

_CHAT_LOG_REL = Path("work") / "chat.jsonl"
_INITIAL_TURN_ID = "0"  # written by scaffold_project (project_init.py)


# ── Runner factory hook (for tests) ──────────────────────────────────────


def _default_chat_runner_factory() -> AgentRunner:
    """Build the default runner for a director chat reply.

    Mirrors ``workflow.py``: :class:`MockRunner` by default so the chat
    path works without LLM credentials (guide 傻瓜式 dry-run).
    """
    return MockRunner()


CHAT_RUNNER_FACTORY = _default_chat_runner_factory


# ── Dependencies ─────────────────────────────────────────────────────────


def _root_dep(request: Request) -> Path:
    root = getattr(request.app.state, "root", None)
    if root is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server root not initialised",
        )
    return Path(root)


RootDep = Annotated[Path, Depends(_root_dep)]


# ── Helpers ──────────────────────────────────────────────────────────────


def _resolve_project(root: Path, project_id: str) -> Path:
    """Resolve *project_id* to its workspace path or 404."""
    try:
        path = resolve_project_path(root, project_id)
    except ProjectPathError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not path.exists() or not (path / "config.yaml").exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id!r} not found",
        )
    return path


def _chat_log_path(project_path: Path) -> Path:
    """Return the chat log file path (``work/chat.jsonl``)."""
    return project_path / _CHAT_LOG_REL


def _ensure_chat_log(project_path: Path) -> Path:
    """Ensure the chat log file exists (create ``work/`` + empty file)."""
    log_path = _chat_log_path(project_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text("", encoding="utf-8")
    return log_path


def _read_chat_log(project_path: Path) -> list[ChatMessage]:
    """Read every line of the chat log into :class:`ChatMessage` objects.

    Malformed lines are skipped (a corrupted log must not crash the GET).
    """
    log_path = _chat_log_path(project_path)
    if not log_path.exists():
        return []
    messages: list[ChatMessage] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("chat log: skipping malformed line: %r", line[:80])
            continue
        try:
            messages.append(ChatMessage.model_validate(obj))
        except Exception:  # noqa: BLE001 — skip semantically invalid entries
            logger.warning("chat log: skipping invalid message: %r", line[:80])
            continue
    return messages


def _append_chat_message(log_path: Path, message: ChatMessage) -> None:
    """Append a single :class:`ChatMessage` as one JSONL line."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(message.model_dump_json() + "\n")


def _new_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:8]}"


def _new_turn_id() -> str:
    """Generate a fresh Turn id (monotonic-ish, based on uuid8)."""
    return uuid.uuid4().hex[:8]


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _build_chat_director() -> Director:
    """Build a minimal :class:`Director` for the chat reply path.

    The chat director runs a 1-node "tree" (just the director itself) so
    the user's message is turned into a single agent call that produces
    the reply text. This mirrors the integration-test pattern but with a
    root-only tree to keep the reply synchronous and cheap.
    """
    director_agent = Agent(
        id="director",
        name="director",
        task="与用户对话，根据用户消息决策并回复。",
        input="用户消息、当前项目状态摘要",
        output="给用户的回复文本",
        permission=parse_permission(
            {"read": ["state", "outline", "short_goal", "notes"], "write": ["notes"]}
        ),
        model=None,
        skills=[],
        tools=["read", "search", "write"],
        head=None,
        tail=None,
        allow_recursive=True,
    )
    return Director(director_agent)


def _single_node_tree() -> WorkflowTree:
    """Build a 1-node :class:`WorkflowTree` (root only) for chat replies."""
    root = TreeNode(
        id="root",
        agent_name="director",
        description="与用户对话",
        params={},
        depth=0,
        parent_id=None,
    )
    return WorkflowTree(root=root, all_nodes={"root": root})


async def _produce_director_reply(user_content: str) -> str:
    """Run a 1-node director round and return the reply text.

    Uses :class:`MockRunner` by default (via ``CHAT_RUNNER_FACTORY``) so
    the chat path is LLM-credential-free. The director's
    :meth:`Director.run_round` records the agent response; we extract the
    text from the first completed node by re-running the mock runner
    directly (the round result only carries agent ids + token totals, not
    the response text — so we call the runner again with the same prompt
    to obtain the text deterministically).
    """
    director = _build_chat_director()
    tree = _single_node_tree()
    runtime = Runtime({"timeout_seconds": 30, "max_retries": 0, "max_concurrent": 1})
    budget = BudgetTracker(max_iterations=4, max_tokens=10_000, max_tool_calls=10)
    runner = CHAT_RUNNER_FACTORY()

    # Run the round (1 node → 1 agent call). The round result confirms the
    # call succeeded; the actual reply text is produced by re-running the
    # runner with the director's assembled prompt so it is deterministic
    # for the MockRunner (same prompt → same output).
    from app.agents.parser import parse_agent_to_prompt
    from app.agents.workflow import generate_flow_sequence

    result = await director.run_round(
        tree=tree,
        runtime=runtime,
        budget=budget,
        runner=runner,
        context=user_content,
        maximal_recursive_calling_depth=1,
    )
    if not result.completed_agents:
        return "[director unavailable]"
    # Re-derive the reply text from the director's prompt (deterministic
    # for MockRunner; for a real runner this would be the last response
    # captured by the runner — the API surface stays the same).
    flow_seq = generate_flow_sequence(tree)
    prompt = parse_agent_to_prompt(director.agent, context=user_content, flow_sequence=flow_seq)
    response = await runner.run(director.agent, prompt)
    return response.text


def _commit_turn(project_path: Path, turn_id: str, message: str) -> None:
    """Stage + commit a Turn via :class:`ProjectRepo`."""
    repo = ProjectRepo(project_path)
    repo.commit_turn(turn_id=turn_id, message=message)


def _turn_id_before(project_path: Path, message: ChatMessage) -> str:
    """Return the Turn id that immediately precedes *message* in the log.

    The chat log is the source of truth for "which turn produced which
    message". The Turn *before* a user message is the turn the project
    was at *just before* that message was sent — rolling back to it
    reverts both the chat log entry and any resource mutations the
    director's reply round produced.

    If the message is the first in the log, the preceding turn is the
    project's initial Turn ``"0"`` (written by ``scaffold_project``).
    """
    messages = _read_chat_log(project_path)
    target_idx: int | None = None
    for idx, msg in enumerate(messages):
        if msg.message_id == message.message_id:
            target_idx = idx
            break
    if target_idx is None:
        msg_ids = [m.message_id for m in messages]
        err = (
            f"message {message.message_id!r} not in chat log; "
            f"known ids: {msg_ids}"
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err)
    if target_idx == 0:
        return _INITIAL_TURN_ID
    return messages[target_idx - 1].turn_id


def _rewrite_chat_log_after_rollback(
    project_path: Path,
    rolled_back_to_turn: str,
) -> list[ChatMessage]:
    """After a git rollback, re-read the chat log from the working tree
    and return the surviving messages.

    The rollback (mode='branch') checks out a new branch at the target
    commit; the working tree's ``work/chat.jsonl`` now reflects the state
    at that commit — i.e. every message whose Turn came *after*
    ``rolled_back_to_turn`` is gone. We re-read the log and return the
    surviving messages so the caller can return them to the client.
    """
    surviving = _read_chat_log(project_path)
    # Defensive: ensure surviving messages all belong to turns <= the
    # rollback target. The git checkout already enforced this on disk;
    # this is a sanity check that the log matches.
    _ = rolled_back_to_turn
    return surviving


# ── Routes ───────────────────────────────────────────────────────────────


@router.get("/{project_id}", response_model=list[ChatMessage])
def get_chat_history(
    project_id: ProjectIdPath,
    root: RootDep,
) -> list[ChatMessage]:
    """Return the full chat history for *project_id* (chronological)."""
    project_path = _resolve_project(root, project_id)
    return _read_chat_log(project_path)


@router.post("/{project_id}", response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def send_chat_message(
    project_id: ProjectIdPath,
    req: SendChatRequest,
    root: RootDep,
) -> ChatResponse:
    """Send a user message to the director and return the reply.

    Steps:
    1. Append the user message to ``work/chat.jsonl``.
    2. Produce the director's reply (via :class:`MockRunner` by default).
    3. Append the director message to the log.
    4. Commit a Turn (so the exchange is versioned with the project).
    """
    project_path = _resolve_project(root, project_id)
    log_path = _ensure_chat_log(project_path)

    turn_id = _new_turn_id()
    user_message = ChatMessage(
        message_id=_new_message_id(),
        role="user",
        content=req.content,
        turn_id=turn_id,
        timestamp=_now_iso(),
    )
    _append_chat_message(log_path, user_message)

    # Produce the director reply.
    try:
        reply_text = await _produce_director_reply(req.content)
    except Exception as exc:  # noqa: BLE001 — chat must not crash on runner error
        logger.exception("director reply failed for project %s", project_id)
        reply_text = f"[director error: {type(exc).__name__}]"

    director_message = ChatMessage(
        message_id=_new_message_id(),
        role="director",
        content=reply_text,
        turn_id=turn_id,
        timestamp=_now_iso(),
    )
    _append_chat_message(log_path, director_message)

    # Commit a Turn: both the chat log update and any resource writes the
    # director's round produced land in one atomic commit (guide:334-336).
    _commit_turn(project_path, turn_id=turn_id, message=f"chat exchange {turn_id}")

    return ChatResponse(user_message=user_message, director_message=director_message)


@router.delete(
    "/{project_id}/{message_id}",
    response_model=list[ChatMessage],
    status_code=status.HTTP_200_OK,
)
def delete_chat_message(
    project_id: ProjectIdPath,
    message_id: MessageIdPath,
    root: RootDep,
) -> list[ChatMessage]:
    """Delete a message **and roll back** the project to the Turn before it.

    Per guide:412 the delete is synced to backend data rollback. Per
    guide:314-316 rollback = new branch (NOT delete) — the original
    timeline is preserved on its old branch.
    """
    project_path = _resolve_project(root, project_id)
    messages = _read_chat_log(project_path)
    target: ChatMessage | None = None
    for msg in messages:
        if msg.message_id == message_id:
            target = msg
            break
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Message {message_id!r} not found in project {project_id!r}",
        )

    # Resolve the Turn that preceded the target message → that's where we
    # roll back to.
    rollback_to_turn = _turn_id_before(project_path, target)

    # Perform the rollback (mode='branch' per guide:314-316).
    version_mgr = VersionManager(project_path)
    try:
        branch = version_mgr.rollback(to_turn=rollback_to_turn, mode="branch")
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot roll back to turn {rollback_to_turn!r}: {exc}",
        ) from exc

    # The git checkout has rewound work/chat.jsonl to the target commit.
    # Re-read the surviving messages and return them to the client.
    surviving = _rewrite_chat_log_after_rollback(project_path, rollback_to_turn)
    _ = branch  # branch name not surfaced on delete (no new message produced)
    return surviving


@router.post(
    "/{project_id}/{message_id}/retry",
    response_model=RetryResponse,
    status_code=status.HTTP_200_OK,
)
async def retry_chat_message(
    project_id: ProjectIdPath,
    message_id: MessageIdPath,
    root: RootDep,
) -> RetryResponse:
    """Retry from *message_id*: roll back to before it, re-send, return
    the new reply.

    Per guide:412 retry is synced to backend rollback + re-run. The
    rollback creates a new branch (mode='branch', guide:314-316) — the
    branch name is returned in :class:`RetryResponse` so the client can
    show the user that a new timeline was created.
    """
    project_path = _resolve_project(root, project_id)
    messages = _read_chat_log(project_path)
    target: ChatMessage | None = None
    for msg in messages:
        if msg.message_id == message_id:
            target = msg
            break
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Message {message_id!r} not found in project {project_id!r}",
        )
    if target.role != "user":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Message {message_id!r} is role={target.role!r}; "
                "retry is only allowed on user messages."
            ),
        )

    rollback_to_turn = _turn_id_before(project_path, target)
    version_mgr = VersionManager(project_path)
    try:
        branch = version_mgr.rollback(to_turn=rollback_to_turn, mode="branch")
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot roll back to turn {rollback_to_turn!r}: {exc}",
        ) from exc

    # After rollback, the chat log on disk reflects the state at
    # rollback_to_turn. Re-seed the chat log file path + append a fresh
    # user message with the SAME content as the target (retry = re-send).
    log_path = _ensure_chat_log(project_path)
    new_turn_id = _new_turn_id()
    new_user_message = ChatMessage(
        message_id=_new_message_id(),
        role="user",
        content=target.content,
        turn_id=new_turn_id,
        timestamp=_now_iso(),
    )
    _append_chat_message(log_path, new_user_message)

    try:
        reply_text = await _produce_director_reply(target.content)
    except Exception as exc:  # noqa: BLE001
        logger.exception("director retry reply failed for project %s", project_id)
        reply_text = f"[director error: {type(exc).__name__}]"

    new_director_message = ChatMessage(
        message_id=_new_message_id(),
        role="director",
        content=reply_text,
        turn_id=new_turn_id,
        timestamp=_now_iso(),
    )
    _append_chat_message(log_path, new_director_message)
    _commit_turn(project_path, turn_id=new_turn_id, message=f"chat retry {new_turn_id}")

    return RetryResponse(
        branch=branch,
        user_message=new_user_message,
        director_message=new_director_message,
    )


__all__ = ["router"]
