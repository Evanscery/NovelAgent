"""Facade module — re-exports public API from split submodules.

The original monolithic card_migration.py has been split into:
- ir_definition.py: CardIR, RuntimePlan TypedDicts
- card_recognition.py: load/is_recognize/infer functions + heuristic helpers
- content_builders.py: _build_*_md resource content builders
- materializer.py: MaterializeResult + materialize_project_from_card + file I/O

All public symbols are re-exported here so existing imports
``from app.compat.tavern_card.card_migration import X`` continue to work.
"""

from __future__ import annotations

from app.compat.tavern_card.card_recognition import (
    infer_card_ir,
    infer_runtime_plan,
    is_recognized_card,
    load_card_payload,
)
from app.compat.tavern_card.ir_definition import CardIR, RuntimePlan
from app.compat.tavern_card.materializer import (
    MaterializeResult,
    materialize_project_from_card,
)

__all__ = [
    "CardIR",
    "MaterializeResult",
    "RuntimePlan",
    "infer_card_ir",
    "infer_runtime_plan",
    "is_recognized_card",
    "load_card_payload",
    "materialize_project_from_card",
]
