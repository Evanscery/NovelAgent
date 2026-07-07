"""AtomicTurn — all-or-nothing Turn commit coordinator (Runtime layer).

Per refactor_guide:334-336 every maintenance-write round of a Workflow
must commit ALL writes atomically or roll back NONE of them.

The ``AtomicTurn`` context manager **coordinates** the transaction; the
data layer (``ProjectRepo``) **performs** the actual git snapshot, commit,
and restore operations.
"""

from __future__ import annotations

from types import TracebackType
from typing import Self

from app.data.project_repo import ProjectRepo


class AtomicTurn:
    """Async context manager that wraps a single Turn as an all-or-nothing unit.

    Usage::

        async with AtomicTurn(repo, "turn-004", "Writer + maintainer writes"):
            await maintainer.write_state(...)
            await maintainer.write_notes(...)
        # On success: a single git commit holds BOTH writes.
        # On exception: the working tree is restored to the pre-turn state.

    The ``async`` flavour is deliberate — the context manager itself is
    synchronous (snapshot/commit are fast local git ops), but it is designed
    to wrap ``await``-able maintainer agent calls. The rest of the runtime
    uses async throughout.
    """

    def __init__(self, project_repo: ProjectRepo, turn_id: str, message: str) -> None:
        self._repo = project_repo
        self._turn_id = turn_id
        self._message = message
        self._snapshot: str | None = None

    # --- async context manager ----------------------------------------------

    async def __aenter__(self) -> Self:
        """Snapshot the current working tree state *before* any writes.

        Records the pre-Turn HEAD SHA (or ``None`` when no commit exists
        yet) so the failure path can restore the working tree to exactly
        this state.
        """
        self._snapshot = self._repo.current_commit()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Commit all writes on success; roll back to snapshot on exception.

        Per refactor_guide:334-336 — all maintainer ops in a Turn either
        commit together or are fully discarded.
        """
        if exc_type is None:
            # All writes succeeded → atomic commit.
            self._repo.commit_turn(self._turn_id, self._message)
        else:
            # An exception occurred → discard every partial write by
            # restoring the working tree to the pre-Turn snapshot.
            self._repo.restore_to(self._snapshot)
