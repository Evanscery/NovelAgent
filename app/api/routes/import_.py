"""/api/import — delegates to app/compat/tavern_card (todo 34 implements).

For now the handler returns ``501 Not Implemented`` with a clear message
so the front-end can wire the button against a stable contract. The
actual card-migration logic lands in todo 34
(``app/compat/tavern_card/card_migration.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.schemas import ImportRequest

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def import_card(req: ImportRequest) -> None:
    """Stub — card import not yet implemented (todo 34)."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Card import not yet implemented (todo 34). "
        "The /api/import endpoint will delegate to app/compat/tavern_card/ "
        "once the ST compat layer lands in todo 34.",
    )


__all__ = ["import_card", "router"]
